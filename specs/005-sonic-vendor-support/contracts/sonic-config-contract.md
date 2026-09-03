# Contract: SONiC Startup-Configuration Output

What `transforms/templates/startup_config_sonic.j2` (SONiC `config` CLI: interfaces, VLAN/VXLAN) and
`transforms/templates/startup_config_sonic_frr.j2` (FRR: BGP underlay + EVPN) must each emit, as two separate
artifacts (`Startup configuration` / `FRR configuration` — see `sonic-registration.md`). Both templates consume
the **unchanged** shared query `transforms/startup_config.gql` and receive exactly the same context as the
other four vendor templates and each other; each renders only the section it owns.

## Data surface

Identical to Juniper's
[junos-config-contract.md](../../003-juniper-junos-support/contracts/junos-config-contract.md) Data surface
section — the shared query is not vendor-specific. Restated here for completeness:

| Path | Notes |
|---|---|
| `device.hostname.value` | |
| `device.asn.value` | may be `none` → fall back to fabric ASN |
| `device.loopback_ip.node.address.ip` | **bare IP, no mask** — router-id, iBGP source, RD prefix |
| `device.pod.node.parent.node` | the Fabric → `.overlay_asn.value`, `.anycast_gateway_mac.value` |
| `device.interfaces.edges[].node` | `.name.value`, `.description.value`, `.role.value`, `.status.value`, `.ip_address.node.address.value` (**CIDR**) |
| `device.bgp_sessions.edges[].node` | `.remote_as.value`, `.rr_client.value`, `.address_family.value`, `.peer_device.node.hostname.value`, `.peer_device.node.loopback_ip.node.address.ip` (`NetworkDevice` peers only), `.peer_device.node.interfaces.edges[].node.ip_address.node.address.value` (`NetworkServer` peers only) |
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

`startup_config_sonic_frr.j2` copies the `device`/`fabric`/`overlay_asn` fallback and the `vns` namespace loop
(materialised VRFs — segments with both a gateway *and* a VRF) from `startup_config_arista.j2`, unchanged.
That loop is the leaf-only gate: spines and super-spines have `device.segments.edges == []`, so every overlay
section disappears for them.

One addition, already present verbatim in the other templates and reused as-is:

- `is_rr` — `device.bgp_sessions.edges | selectattr("node.rr_client.value") | list | length > 0`.

`vns` and `is_rr` are used only in FRR sections, so `startup_config_sonic.j2` (the config-CLI template) needs
neither — its preamble is just the `device` line. Both templates independently derive `overlay_asn` from
`device`/`fabric`, since each is rendered as its own separate context, not shared state between two sections
of one file.

**Not reused**: the anycast-MAC normalisation three-liner Arista/Dell/Juniper carry. Those three vendors
render an explicit anycast-gateway MAC on the leaf SVI (`ip virtual-router mac-address` / `virtual-gateway-v4-mac`).
SONiC's equivalent is its Static Anycast Gateway (SAG) feature, whose exact `config`/FRR syntax was not
confirmed with enough certainty to render here without guessing — see Out of scope.

## Structural rule: two dialects, two artifacts, no cross-contamination

This is where the SONiC template departs from the other four, and it is a **milder** departure than Junos's:
there is no brace-nesting risk, because neither dialect SONiC actually uses is hierarchical.

1. **SONiC `config` CLI** (`startup_config_sonic.j2`, artifact `Startup configuration`) — imperative, one
   command per line, in the same flat style Arista's `interface <name>` block already uses per interface (loop
   `device.interfaces.edges` **unfiltered**, exactly like Cisco/Arista/Dell — SONiC needs no per-role interface
   collection the way Junos's `lo0` did).
2. **FRR routing** (`startup_config_sonic_frr.j2`, artifact `FRR configuration`) — `router bgp <asn>` in FRR's
   Cisco-like flat CLI syntax, structurally close to `startup_config_arista.j2`'s own `router bgp` block.

The two dialects render into **separate artifacts**, one template each, rather than sharing one file with
banner comments (research.md D5, revised): there is no single native SONiC "show running-config" equivalent
that unifies them, and real SONiC applies the two through genuinely separate mechanisms — `config`
CLI/`config_db.json` (the `swss` container) versus `vtysh`/`frr.conf` (the `bgp` container). Splitting removes
the risk a single combined file carried — a `config` CLI verb rendered where an FRR verb belongs, or vice versa
— entirely, since each artifact can only contain its own dialect's Jinja branches. Both templates share the
`device`/`fabric`/`overlay_asn` preamble (recomputed independently in each file, since each is a separate
render); `startup_config_sonic.j2` does not need `vns`/`is_rr`/`evpn_sessions`/`ipv4_sessions` at all — those
are used only in the FRR sections, so they belong solely in `startup_config_sonic_frr.j2`'s preamble.

**Never** emit `config interface ... Loopback1` or any command naming the VTEP loopback literally as an
interface — it is a logical name in the data model; **interface `role` is the discriminator**, exactly as
established for Juniper. The `vtep`-role interface's address is the VXLAN tunnel source, not a second routed
loopback interface in SONiC's own model.

## Required output by section

Gating: `{% if overlay_asn is not none %}` guards the BGP/EVPN sections; `{% if device.segments.edges %}`
guards every tenant-overlay section. Both gates already exist in the other four templates, and both templates
recompute `overlay_asn` independently in their own preamble.

### Always — SONiC `config` CLI, per interface (unfiltered loop, excluding `loopback`/`vtep` roles) — `startup_config_sonic.j2`

The interface loop itself is unfiltered — every physical/access interface (`super_spine`, `spine`, `leaf`,
`server`, `storage`) gets description/admin-state — but the `loopback`- and `vtep`-role interfaces are
explicitly **excluded** from this loop's body. Neither is a real configured SONiC interface object: the
routing loopback is addressed via the dedicated `Loopback0` line below, and the VTEP source is a bare IP
argument to `config vxlan add`, not an interface. Rendering `config interface description Loopback1 ...`
would violate the "never name the VTEP loopback as a literal interface" rule above.

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

### When `overlay_asn` is set — FRR EVPN control plane, all tiers — `startup_config_sonic_frr.j2`

**Sessions split by `address_family`, load-bearing not cosmetic** — the same split every other vendor's
template makes: an EVPN session is iBGP to the peer's *loopback*; an attached server's `ipv4_unicast` session
is eBGP to the `/31` on the peer's own interface. Only a `NetworkDevice` peer exposes `loopback_ip`; letting a
server session through the EVPN loop dereferences a field its peer (`NetworkServer`) does not have and fails
the whole artifact. `evpn_sessions` = everything except `address_family.value == "ipv4_unicast"`;
`ipv4_sessions` = only those. A spine/super-spine never has `ipv4_sessions` (servers attach to leaves only),
so this only actually matters on leaves — but the template cannot assume that and must filter unconditionally.

```text
router bgp <overlay_asn>
 bgp router-id <loopback_ip>
 no bgp default ipv4-unicast
 neighbor <evpn peer loopback ip> remote-as <remote_as or overlay_asn>          # evpn_sessions
 neighbor <evpn peer loopback ip> update-source Loopback0
 neighbor <evpn peer loopback ip> send-community extended
 ...
 neighbor <ipv4 peer's own /31 address> remote-as <remote_as>                  # ipv4_sessions
 ...
 address-family l2vpn evpn
  neighbor <evpn peer loopback ip> activate                                    # evpn_sessions only
  neighbor <evpn peer loopback ip> route-reflector-client        # only when is_rr, per session with rr_client
  advertise-all-vni
 exit-address-family
 address-family ipv4 unicast                                                   # only if ipv4_sessions non-empty
  neighbor <ipv4 peer's own /31 address> activate
 exit-address-family
exit
```

The `ipv4_sessions` peer address is not on the session itself — derive it the same way Arista/Juniper do: scan
`session.peer_device.node.interfaces.edges` for the first interface carrying an `ip_address`, take the address
minus its mask (`.split("/")[0]`).

Iterate sessions with `| sort(attribute="node.peer_device.node.hostname.value")` — the determinism guard all
four existing templates use, required so unrelated re-renders produce byte-identical output.

Per-session AS fallback for EVPN sessions only, identical to the other four:
`session.remote_as.value if session.remote_as.value is not none else overlay_asn`. `ipv4_sessions` always
carry an explicit `remote_as` (the server's own ASN) — no fallback needed there.

### Leaves only — tenant overlay

SONiC `config` CLI (VLAN, SVI, VRF binding, VXLAN) — `startup_config_sonic.j2`:

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

FRR (per-L2VNI RD/route-target, plus the L3VNI/VRF binding) — `startup_config_sonic_frr.j2`, guarded by both
`device.segments.edges` **and** its own nested `overlay_asn is not none` check (not just the outer BGP-section
gate — a leaf with segments but no `overlay_asn` must still emit zero FRR content):

```text
router bgp <overlay_asn>
 address-family l2vpn evpn
  vni <l2vni>
   rd <loopback_ip>:<vlan_id>
   route-target both <segment route_target>
  exit-vni
  ...
 exit-address-family
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

These map directly to spec FR-006/FR-007/FR-008 and are what the SC-001 reviewer checks. Rules marked
**(pair)** span both artifacts — check them against `Startup configuration` and `FRR configuration` fetched
together for the same device, not either artifact in isolation.

| # | Rule |
|---|---|
| A1 | Every SONiC `config` CLI line (`Startup configuration`) is a complete, independently valid command — no partial/continuation lines. |
| A2 **(pair)** | A **leaf** with segments emits, in `Startup configuration`: `config vlan add`, `config vxlan map add`, and (for gateway-bearing segments) `config interface ip add Vlan<id>` + `config interface vrf bind`; and, in `FRR configuration`: an FRR `vrf <name> / vni <l3vni>` block. |
| A3 **(pair)** | A **spine or super-spine**'s `FRR configuration` emits the `router bgp` / `address-family l2vpn evpn` block but **no** `vrf ... vni ...` block; its `Startup configuration` has **no** `config vlan` and **no** `config vxlan` line at all. |
| A4 **(pair)** | `config vxlan add vtep1 <ip>` (`Startup configuration`) uses the device's `vtep`-role interface address; FRR `bgp router-id` and `update-source` (`FRR configuration`) use the `loopback`-role address — the two are never the same line, and never in the same artifact. |
| A5 | A segment with **no** gateway still gets `config vlan add` and `config vxlan map add` (`Startup configuration`), but **no** `config interface ip add Vlan<id>` and **no** `config interface vrf bind` line. |
| A6 | `route-reflector-client` (`FRR configuration`) appears only on sessions with `rr_client` true, and only on devices that have at least one such session. |
| A7 | Uncabled interfaces still get a `config interface description`/`shutdown` pair (`Startup configuration`) — never omitted, matching the "present but disabled" contract every other vendor already has. |
| A8 | Re-rendering an unchanged device produces byte-identical output for **both** artifacts independently (session and VNI iteration order is deterministic). |
| A9 | Every SONiC device has **exactly two** artifacts — `Startup configuration` and `FRR configuration` — never zero, one, or more than two (FR-006, SC-003; the other four vendors still have exactly one). |

## Out of scope for this template

Interface MTU; realistic management (`eth0`) addressing; AAA/NTP/syslog; per-server access-port VLAN
membership (`config vlan member add`) — the template renders VLANs and their VNI maps, not the individual
tagging commands for every server-facing port, which is not information the shared query provides per
segment; any change to the shared query. **A rendered anycast-gateway MAC on the leaf SVI** — Arista and
Juniper both render one (`ip virtual-router mac-address` / `virtual-gateway-v4-mac`); SONiC's Static Anycast
Gateway (SAG) feature is the real equivalent, but its exact `config`/FRR command syntax was not confirmed
with enough certainty to render here without guessing, so it is deliberately omitted rather than guessed.
Flag explicitly for the SC-001 reviewer — this is a genuine fidelity gap relative to two of the four existing
vendors, not a neutral simplification shared by all five.
