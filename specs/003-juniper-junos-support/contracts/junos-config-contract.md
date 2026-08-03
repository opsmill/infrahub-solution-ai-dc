# Contract: Junos Startup-Configuration Output

What `transforms/templates/startup_config_juniper.j2` must emit. The template consumes the **unchanged**
shared query `transforms/startup_config.gql` and receives exactly the same context as the other three vendor
templates.

## Data surface

Everything hangs off `data.NetworkDevice.edges[0].node`. This is the complete set of paths available; no
other field is queried.

| Path | Notes |
|---|---|
| `device.hostname.value` | |
| `device.asn.value` | may be `none` → fall back to fabric ASN |
| `device.loopback_ip.node.address.ip` | **bare IP, no mask** — router-id, iBGP source, RD prefix |
| `device.pod.node.parent.node` | the Fabric → `.overlay_asn.value`, `.anycast_gateway_mac.value` |
| `device.interfaces.edges[].node` | `.name.value`, `.description.value`, `.role.value`, `.status.value`, `.ip_address.node.address.value` (**CIDR**) |
| `device.bgp_sessions.edges[].node` | `.remote_as.value`, `.rr_client.value`, `.peer_device.node.hostname.value`, `.peer_device.node.loopback_ip.node.address.ip` |
| `device.segments.edges[].node` | `.name.value`, `.vlan_id.value`, `.l2vni.value`, `.route_target.value`, `.gateway.node.address.value` |
| `segment.vrf.node` | `.name.value`, `.l3vni.value`, `.route_target.value`, `.l3_vlan_id.value` (**not used** — see below) |

Interface `role` values that matter: `super_spine`, `spine`, `leaf` (physical underlay links), `loopback`
(lo0.0), `vtep` (lo0.1), and access roles (`server`, `storage`) which carry no IP.
Interface `status` value that matters: `"inactive"`.

**Queried but deliberately unused**: `device.role.value`, `device.vtep_ip`, `segment.routed`,
`segment.subnet`, `vrf.l3_vlan_id` (Junos symmetric IRB binds the L3VNI to the routing instance directly —
only the Cisco template renders a transit VLAN).

**Not available**: `NetworkInterface.mtu` exists in the schema but is not in the query and is rendered by no
vendor. Out of scope.

## Preamble

Copy lines 1-12 of `startup_config_arista.j2` verbatim — `device`, `fabric`, the `overlay_asn` fallback, and
the `vns` namespace loop that de-duplicates **materialised VRFs** (segments that have a gateway *and* a VRF).
That loop is the leaf-only gate: spines and super-spines have `device.segments.edges == []`, so every overlay
section disappears for them.

Two additions:

- `is_rr` — copy from `startup_config_cisco.j2:13`:
  `device.bgp_sessions.edges | selectattr("node.rr_client.value") | list | length > 0`
- **Anycast MAC normalisation** — copy the three-liner from `startup_config_dell.j2:13-15`. Junos wants
  colon-delimited MACs exactly as OS10 does. Default `"0000.5e00.0001"` when the fabric value is unset,
  matching all three existing templates.

## Structural rule: `lo0` must be collected, not looped

This is the one place the Juniper template genuinely departs from the other three, and the most likely source
of a defect.

Cisco/Arista/Dell iterate `device.interfaces.edges` **unfiltered** and emit one flat
`interface {{ name }}` stanza per interface (`startup_config_arista.j2:39-41`). Junos cannot do that: both
loopbacks are **units of a single `lo0`**. The template must therefore:

1. Emit physical interfaces (roles `super_spine`/`spine`/`leaf`, plus access roles) inside `interfaces { }`.
2. Emit **one** `lo0 { }` stanza containing `unit 0` for the `loopback`-role interface and `unit 1` for the
   `vtep`-role interface (leaves only — spines have no vtep interface).
3. Never emit `interface Loopback0` or `interface Loopback1` literally. `Loopback0`/`Loopback1` are logical
   names in the data model; **interface `role` is the discriminator** (`CONTEXT.md`, flagged-ambiguities).

## Required output by section

Gating: `{% if overlay_asn is not none %}` guards the BGP/EVPN sections; `{% if device.segments.edges %}`
guards every tenant-overlay section. Both gates already exist in the other three templates.

### Always

```junos
system {
    host-name <device.hostname.value>;
}
interfaces {
    <name> {                                   /* roles super_spine|spine|leaf */
        description "<description>";           /* if set */
        disable;                               /* if status == "inactive" */
        unit 0 {
            family inet { address <ip_address CIDR>; }   /* if ip_address present */
        }
    }
    ...
    lo0 {
        unit 0 { family inet { address <loopback_ip>/32; } }
        unit 1 { family inet { address <vtep ip CIDR>; } }   /* leaves only */
    }
    em0 {
        unit 0 { family inet { address <loopback_ip>/32; } }
    }
}
routing-options {
    router-id <loopback_ip>;
    autonomous-system <overlay_asn>;
}
protocols {
    ospf {
        area 0.0.0.0 {
            interface lo0.0 { passive; }
            interface <name>.0 { interface-type p2p; }   /* per active underlay link */
        }
    }
}
```

> `em0` reusing the loopback IP as the management address mirrors the existing three templates, which all do
> the same (`interface mgmt0` / `Management1` / `mgmt1/1/1`). It is a known repo-wide simplification and is
> explicitly outside the SC-001 review mandate.

### When `overlay_asn` is set — EVPN control plane, all tiers

```junos
protocols {
    bgp {
        group EVPN-OVERLAY {
            type internal;
            local-address <loopback_ip>;
            family evpn { signaling; }
            cluster <loopback_ip>;                    /* only when is_rr */
            neighbor <peer loopback ip> {
                peer-as <remote_as or overlay_asn>;
            }
            ...
        }
    }
    /* leaves only -- gated on device.segments.edges, since `encapsulation vxlan`
       requires switch-options vtep-source-interface */
    evpn {
        encapsulation vxlan;
        extended-vni-list [ <l2vni> ... ];
        vni-options {
            vni <l2vni> { vrf-target target:<segment route_target>; }
        }
    }
}
```

Iterate sessions with `| sort(attribute="node.peer_device.node.hostname.value")` — the determinism guard all
three existing templates use, required so unrelated re-renders produce byte-identical output.

Per-session AS fallback, identical to the other three:
`session.remote_as.value if session.remote_as.value is not none else overlay_asn`.

A single BGP group is correct here: every device's sessions are uniform (spines are RRs for all their
clients; leaves have no rr_client sessions), so `cluster` is safely group-level.

### Leaves only — tenant overlay

```junos
interfaces {
    irb {
        unit <vlan_id> {                                   /* only segments WITH a gateway */
            family inet {
                address <gateway CIDR> { virtual-gateway-address <gateway ip>; }
            }
            virtual-gateway-v4-mac <normalised anycast mac>;
        }
    }
}
switch-options {
    vtep-source-interface lo0.1;
    route-distinguisher <loopback_ip>:1;
}
vlans {
    <segment name> {
        vlan-id <vlan_id>;
        l3-interface irb.<vlan_id>;                        /* OMIT when the segment has no gateway */
        vxlan { vni <l2vni>; }
    }
}
routing-instances {
    <vrf name> {
        instance-type vrf;
        interface irb.<vlan_id>;                           /* per gateway-bearing segment in this VRF */
        route-distinguisher <loopback_ip>:<l3vni>;
        vrf-target target:<vrf route_target>;
        protocols { evpn { irb-symmetric-routing { vni <l3vni>; } } }
    }
}
```

## Acceptance rules

These map directly to spec FR-006/FR-007/FR-008 and are what the SC-001 reviewer checks.

| # | Rule |
|---|---|
| A1 | Braces balance to zero and never go negative. |
| A2 | A **leaf** with segments emits `switch-options`, `vlans`, `routing-instances`, and `irb` units. |
| A3 | A **spine or super-spine** emits `protocols bgp` but **no** `protocols evpn`, **no** `switch-options`, **no** `vlans`, **no** `routing-instances`, **no** `irb`. (Corrected during implementation: `protocols evpn { encapsulation vxlan; }` requires `switch-options vtep-source-interface`, so emitting it on a non-VTEP would fail to commit. It is gated on `device.segments.edges` alongside the other overlay sections.) |
| A4 | `vtep-source-interface` is `lo0.1`; BGP `local-address` is the `lo0.0` address. |
| A5 | A segment with **no** gateway still gets a `vlans` entry with its VNI, but **no** `l3-interface` line and no `irb` unit. |
| A6 | `cluster` appears only on devices that have at least one `rr_client` session. |
| A7 | Uncabled interfaces render as present-but-`disable`d with no `family inet` address — never omitted. |
| A8 | Re-rendering an unchanged device produces byte-identical output (session sort order is deterministic). |

## Out of scope for this template

Interface MTU; realistic management addressing; AAA/NTP/syslog; MAC-VRF; the VRF transit VLAN
(`vrf.l3_vlan_id`); any change to the shared query.
