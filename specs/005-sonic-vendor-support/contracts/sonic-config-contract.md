# Contract: SONiC Startup-Configuration Output

What `transforms/templates/startup_config_sonic.j2` must emit. The template consumes the **unchanged** shared
query `transforms/startup_config.gql` and receives exactly the same context as the other four vendor
templates.

## Data surface

Identical to [junos-config-contract.md](./junos-config-contract.md)'s Data surface section — the shared query
is not vendor-specific. Restated here for completeness:

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

Interface `role` values that matter: `super_spine`, `spine`, `leaf` (physical underlay links), `loopback`,
`vtep` (never rendered as a literal `interface Loopback1` — see Loopbacks below), and access roles (`server`,
`storage`) which carry no IP. Interface `status` value that matters: `"inactive"`.

**Queried but deliberately unused**: `device.role.value`, `device.vtep_ip`, `segment.routed`,
`segment.subnet`, `vrf.l3_vlan_id` (SONiC's symmetric-IRB EVPN model binds the L3VNI to the VRF's FRR `vni`
statement directly — only the Cisco template renders a transit VLAN).

**Not available**: `NetworkInterface.mtu` exists in the schema but is not in the query and is rendered by no
vendor. Out of scope.

## Preamble

Copy the `device`/`fabric`/`overlay_asn` fallback and the `vns` namespace loop (materialised VRFs — segments
with both a gateway *and* a VRF) from `startup_config_arista.j2`, unchanged. That loop is the leaf-only gate:
spines and super-spines have `device.segments.edges == []`, so every overlay section disappears for them.

Two additions, both already present verbatim in the other templates and reused as-is:

- `is_rr` — `device.bgp_sessions.edges | selectattr("node.rr_client.value") | list | length > 0`.
- **Anycast MAC normalisation** — the colon-delimited conversion FRR/Linux expects, same as Arista and Dell
  use. Default `"0000.5e00.0001"` when the fabric value is unset.

## Structural rule: two dialects, one artifact, no nesting

This is where the SONiC template departs from the other four, and it is a **milder** departure than Junos's:
there is no brace-nesting risk, because neither dialect SONiC actually uses is hierarchical.

1. **SONiC `config` CLI section** — imperative, one command per line, in the same flat style Arista's
   `interface <name>` block already uses per interface (loop `device.interfaces.edges` **unfiltered**, exactly
   like Cisco/Arista/Dell — SONiC needs no per-role interface collection the way Junos's `lo0` did).
2. **FRR routing section** — `router bgp <asn>` in FRR's Cisco-like flat CLI syntax, structurally close to
   `startup_config_arista.j2`'s own `router bgp` block.

Both sections go in the same artifact, clearly separated, because there is no single native SONiC "show
running-config" equivalent that unifies them — this is the closest honest single-file representation (see
research.md D5).

**Never** emit `config interface ... Loopback1` or any command naming the VTEP loopback literally as an
interface — it is a logical name in the data model; **interface `role` is the discriminator**, exactly as
established for Juniper. The `vtep`-role interface's address is the VXLAN tunnel source, not a second routed
loopback interface in SONiC's own model.

## Required output by section

Gating: `{% if overlay_asn is not none %}` guards the BGP/EVPN sections; `{% if device.segments.edges %}`
guards every tenant-overlay section. Both gates already exist in the other four templates.

### Always — SONiC `config` CLI, per interface (unfiltered loop)

```text
config interface description <name> "<description>"          # if set, e.g. Eth1/1
config interface startup <name>                               # if status != "inactive"
config interface shutdown <name>                               # if status == "inactive"
config interface ip add <name> <ip_address CIDR>                # if ip_address present, roles super_spine|spine|leaf|server
```

Plus, once per device:

```text
config interface ip add Loopback0 <loopback_ip>/32
```

> There is no per-device management-interface equivalent to render here (unlike Junos's `em0` or Arista's
> `Management1`) — the other templates already treat management addressing as a known, repo-wide
> simplification, and SONiC's `eth0` OOB port is out of scope for the same reason.

### When `overlay_asn` is set — FRR EVPN control plane, all tiers

```text
router bgp <overlay_asn>
 bgp router-id <loopback_ip>
 no bgp default ipv4-unicast
 neighbor <peer loopback ip> remote-as <remote_as or overlay_asn>
 neighbor <peer loopback ip> update-source Loopback0
 ...
 address-family l2vpn evpn
  neighbor <peer loopback ip> activate
  neighbor <peer loopback ip> route-reflector-client        # only when is_rr, per session with rr_client
  advertise-all-vni
 exit-address-family
exit
```

Iterate sessions with `| sort(attribute="node.peer_device.node.hostname.value")` — the determinism guard all
four existing templates use, required so unrelated re-renders produce byte-identical output.

Per-session AS fallback, identical to the other four:
`session.remote_as.value if session.remote_as.value is not none else overlay_asn`.

### Leaves only — tenant overlay

SONiC `config` CLI (VLAN, SVI, VRF binding, VXLAN):

```text
config vlan add <vlan_id>                                         # every segment
config vlan member add <vlan_id> <access-interface> -u             # not rendered here -- access-port
                                                                     # membership is out of scope; the
                                                                     # template renders the VLAN and its
                                                                     # VNI map, not per-server tagging
config interface ip add Vlan<vlan_id> <gateway CIDR>                # only segments WITH a gateway
config interface vrf bind Vlan<vlan_id> <vrf name>                  # only segments WITH a gateway
config vxlan add vtep1 <vtep ip>                                    # once per device, from the vtep-role interface
config vxlan evpn_nvo add nvo1 vtep1                                # once per device
config vxlan map add vtep1 <vlan_id> <l2vni>                        # every segment, gateway or not
```

FRR (per-L2VNI RD/route-target, plus the L3VNI/VRF binding):

```text
router bgp <overlay_asn>
 address-family l2vpn evpn
  vni <l2vni>
   rd <loopback_ip>:<vlan_id>
   route-target both <segment route_target>
  exit-vni
  ...
exit

vrf <vrf name>
 vni <vrf l3vni>
exit-vrf
```

> The `vrf <name> / vni <l3vni> / exit-vrf` block is FRR's top-level VRF-to-L3VNI binding, separate from
> `router bgp`. It is the SONiC/FRR equivalent of Junos's `irb-symmetric-routing { vni ... }` and Arista's
> `vxlan vrf <name> vni <l3vni>` — every vendor expresses the same L3VNI-to-VRF binding, in that vendor's own
> syntax.

## Acceptance rules

These map directly to spec FR-006/FR-007/FR-008 and are what the SC-001 reviewer checks.

| # | Rule |
|---|---|
| A1 | Every SONiC `config` CLI line is a complete, independently valid command — no partial/continuation lines. |
| A2 | A **leaf** with segments emits `config vlan add`, `config vxlan map add`, and (for gateway-bearing segments) `config interface ip add Vlan<id>` + `config interface vrf bind` + an FRR `vrf <name> / vni <l3vni>` block. |
| A3 | A **spine or super-spine** emits the FRR `router bgp` / `address-family l2vpn evpn` block but **no** `config vlan`, **no** `config vxlan`, **no** `vrf ... vni ...` block anywhere in the artifact. |
| A4 | `config vxlan add vtep1 <ip>` uses the device's `vtep`-role interface address; FRR `bgp router-id` and `update-source` use the `loopback`-role address — the two are never the same line. |
| A5 | A segment with **no** gateway still gets `config vlan add` and `config vxlan map add`, but **no** `config interface ip add Vlan<id>` and **no** `config interface vrf bind` line. |
| A6 | `route-reflector-client` appears only on sessions with `rr_client` true, and only on devices that have at least one such session. |
| A7 | Uncabled interfaces still get a `config interface description`/`shutdown` pair — never omitted, matching the "present but disabled" contract every other vendor already has. |
| A8 | Re-rendering an unchanged device produces byte-identical output (session and VNI iteration order is deterministic). |

## Out of scope for this template

Interface MTU; realistic management (`eth0`) addressing; AAA/NTP/syslog; per-server access-port VLAN
membership (`config vlan member add`) — the template renders VLANs and their VNI maps, not the individual
tagging commands for every server-facing port, which is not information the shared query provides per
segment; any change to the shared query.
