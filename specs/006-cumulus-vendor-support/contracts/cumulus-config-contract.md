# Contract: Cumulus Linux Startup-Configuration Output

What `transforms/templates/startup_config_cumulus.j2` must emit. The template consumes the **unchanged**
shared query `transforms/startup_config.gql` and receives exactly the same context as the other five vendor
templates.

## Data surface

Identical to SONiC's
[sonic-config-contract.md](../../005-sonic-vendor-support/contracts/sonic-config-contract.md) Data surface
section — the shared query is not vendor-specific. Restated here for completeness:

| Path | Notes |
|---|---|
| `device.hostname.value` | |
| `device.asn.value` | may be `none` → fall back to fabric ASN |
| `device.loopback_ip.node.address.ip` | **bare IP, no mask** — router-id, iBGP source, RD prefix |
| `device.pod.node.parent.node` | the Fabric → `.overlay_asn.value` |
| `device.interfaces.edges[].node` | `.name.value`, `.description.value`, `.role.value`, `.status.value`, `.ip_address.node.address.value` (**CIDR**) |
| `device.bgp_sessions.edges[].node` | `.remote_as.value`, `.rr_client.value`, `.address_family.value`, `.peer_device.node.hostname.value`, `.peer_device.node.loopback_ip.node.address.ip` (`NetworkDevice` peers only), `.peer_device.node.interfaces.edges[].node.ip_address.node.address.value` (`NetworkServer` peers only) |
| `device.segments.edges[].node` | `.name.value`, `.vlan_id.value`, `.l2vni.value`, `.route_target.value`, `.gateway.node.address.value` |
| `segment.vrf.node` | `.name.value`, `.l3vni.value` |

Interface `role` values that matter: `super_spine`, `spine`, `leaf` (physical underlay links), `loopback`,
`vtep` (never rendered as a literal `iface Loopback1` — see Loopbacks below), and access roles (`server`,
`storage`) which carry no IP. Interface `status` value that matters: `"inactive"`.

**Queried but deliberately unused**: `device.role.value`, `device.vtep_ip`, `segment.routed`,
`segment.subnet`, `vrf.l3_vlan_id` — same reasoning as SONiC: the L3VNI is bound to the VRF via FRR's own
`vrf <name> / vni <l3vni>` static binding, not a transit VLAN.

**Not available**: `NetworkInterface.mtu` exists in the schema but is not in the query and is rendered by no
vendor. Out of scope.

## Preamble

Copy the `device`/`fabric`/`overlay_asn` fallback, the `vns` namespace loop (materialised VRFs — segments
with both a gateway *and* a VRF), the `is_rr` flag, and the `evpn_sessions`/`ipv4_sessions` address-family
split from `startup_config_sonic.j2`, unchanged — all four are vendor-neutral Jinja preamble logic, not SONiC
syntax, and this template needs exactly the same shape (research.md D5: the FRR half of this template is the
same syntax and the same risk class as SONiC's FRR section).

**Not reused**: the anycast-MAC normalisation Arista/Dell/Juniper carry, and SONiC's SAG omission note — see
Out of scope below for the Cumulus equivalent.

## Structural rule: ifupdown2 stanzas + FRR flat CLI, no cross-contamination

This is where the Cumulus template departs from the other five (research.md D5) — a **third** distinct
structural risk, different from both Junos's arbitrary-depth brace nesting and SONiC's two-flat-dialects
split:

1. **`/etc/network/interfaces` (ifupdown2) section** — declarative **stanzas**. Every stanza is:
   - an `auto <name>` line — **present only when the interface is administratively up** (SONiC's
     `status == "inactive"` distinction maps here to *omitting* `auto <name>` rather than emitting a separate
     "shutdown" verb);
   - an `iface <name>` header line;
   - zero or more indented attribute lines belonging **only** to that stanza;
   - a blank line separating it from the next stanza.

   The risk unique to this format: an attribute line rendered outside its owning stanza's indented block
   (e.g. after the blank-line separator, or inside the wrong `iface` block) silently merges into the wrong
   interface or is dropped by the parser — not a wrong-dialect verb (SONiC's risk) and not a wrong-nesting-depth
   brace (Junos's risk), but a **misattributed stanza line**. Keep every stanza's attribute lines contiguous
   and indented, with no other stanza's header line interleaved.
2. **FRR routing section** — `router bgp <asn>` in FRR's flat CLI syntax, byte-for-byte structurally identical
   to `startup_config_sonic.j2`'s own FRR section, because it is the same daemon.

Both sections go in the same artifact, clearly separated, because a real Cumulus Linux device's running
configuration is genuinely split across `/etc/network/interfaces` and `/etc/frr/frr.conf` — this is the
closest honest single-file representation (research.md D5).

**Never** emit an `iface Loopback1` stanza or any command naming the VTEP loopback literally as a separate
interface — it is a logical name in the data model; **interface `role` is the discriminator**, exactly as
established for Juniper and SONiC. The `vtep`-role interface's address becomes a second `address` line inside
the single `lo` stanza (research.md D4), not a second loopback interface.

## Required output by section

Gating: `{% if overlay_asn is not none %}` guards the BGP/EVPN sections; `{% if device.segments.edges %}`
guards every tenant-overlay section. Both gates already exist in the other five templates.

### Always — `/etc/network/interfaces`, per physical interface (unfiltered loop, excluding `loopback`/`vtep` roles)

The interface loop itself is unfiltered — every physical/access interface (`super_spine`, `spine`, `leaf`,
`server`, `storage`) gets a stanza — but the `loopback`- and `vtep`-role interfaces are explicitly **excluded**
from this loop's body, exactly as SONiC excludes them from its per-interface `config` CLI loop, for the same
reason: neither is a real separate Cumulus Linux interface object.

```text
auto <name>                                    # only when status != "inactive"
iface <name>
    alias <description>                        # if description is set
    address <ip_address CIDR>                  # if ip_address present, roles super_spine|spine|leaf|server
```

For an interface with `status == "inactive"`, omit the `auto <name>` line entirely and add `link-down yes`
inside the stanza — Cumulus Linux's ifupdown2 still renders the `iface` stanza (so the interface is
described and its port role is visible), but the missing `auto` line and `link-down yes` together are what
keep it administratively down, matching the "present but disabled" contract every other vendor already has.

```text
iface <name>
    alias <description>                        # if set
    link-down yes
```

Plus, once per device — the `lo` stanza (research.md D4):

```text
auto lo
iface lo
    address <loopback_ip>/32
    address <vtep_ip>/32                        # only if a leaf has an addressed vtep-role interface
```

> There is no per-device management-interface equivalent to render here (unlike Junos's `em0` or Arista's
> `Management1`) — the other templates already treat management addressing as a known, repo-wide
> simplification, and Cumulus Linux's `eth0` OOB port is out of scope for the same reason.

### When `overlay_asn` is set — FRR EVPN control plane, all tiers

Identical shape and identical `evpn_sessions`/`ipv4_sessions` split to
[sonic-config-contract.md](../../005-sonic-vendor-support/contracts/sonic-config-contract.md)'s own section —
same daemon, same risk, same fix already applied there (SONiC research.md D13, defect 2). Restated:

```text
router bgp <overlay_asn>
 bgp router-id <loopback_ip>
 no bgp default ipv4-unicast
 neighbor <evpn peer loopback ip> remote-as <remote_as or overlay_asn>          # evpn_sessions
 neighbor <evpn peer loopback ip> update-source lo
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

`update-source lo` is Cumulus Linux's own loopback interface name — the one difference from SONiC's
`update-source Loopback0` line, both naming the same routing-loopback role.

The `ipv4_sessions` peer address is derived the same way SONiC/Arista/Juniper do: scan
`session.peer_device.node.interfaces.edges` for the first interface carrying an `ip_address`, take the address
minus its mask (`.split("/")[0]`).

Iterate sessions with `| sort(attribute="node.peer_device.node.hostname.value")` — the determinism guard all
five existing templates use.

### Leaves only — tenant overlay

`/etc/network/interfaces` (VLAN-aware bridge, per-segment VNI stanza, routed SVI, VXLAN tunnel source):

```text
auto bridge
iface bridge
    bridge-vlan-aware yes
    bridge-ports vni<l2vni> vni<l2vni> ...      # every segment's VNI interface; physical access-port
                                                  # membership is out of scope (see below)
    bridge-vids <vlan_id> <vlan_id> ...          # every segment, space-separated

auto vni<l2vni>                                  # every segment, gateway or not
iface vni<l2vni>
    vxlan-id <l2vni>
    vxlan-local-tunnelip <vtep ip>
    bridge-access <vlan_id>

auto vlan<vlan_id>                               # only segments WITH a gateway
iface vlan<vlan_id>
    address <gateway CIDR>
    vlan-raw-device bridge
    vlan-id <vlan_id>
    vrf <vrf name>
```

If no addressed `vtep`-role interface is found, render a loud comment instead of a malformed
`vxlan-local-tunnelip` line, the same defensive pattern SONiC's D13 (defect 4) established:

```text
# ERROR: no addressed vtep-role interface found on <hostname> -- VXLAN tunnel cannot be configured
```

FRR (per-L2VNI RD/route-target, plus the L3VNI/VRF binding) — identical shape to SONiC's own tenant-overlay
FRR block, including its own `overlay_asn is not none` guard (SONiC D13, defect 3 — this block must carry its
own guard, not rely on the outer one):

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

> The `vrf <name> / vni <l3vni> / exit-vrf` block is FRR's top-level VRF-to-L3VNI static binding — the same
> construct SONiC's template already uses, reused here unchanged because Cumulus Linux runs the identical FRR
> daemon (research.md D5). This is a deliberate simplification relative to the alternative
> `router bgp <asn> vrf <name>` per-VRF BGP instance some Cumulus EVPN reference designs also use — see Out of
> scope.

## Acceptance rules

These map directly to spec FR-006/FR-007/FR-008 and are what the SC-001 reviewer checks.

| # | Rule |
|---|---|
| A1 | Every `/etc/network/interfaces` stanza is complete — an `iface <name>` header followed only by that interface's own indented attribute lines, terminated by a blank line before the next stanza. |
| A2 | A **leaf** with segments emits `auto bridge`/`iface bridge`, one `vni<l2vni>` stanza per segment, and (for gateway-bearing segments) a `vlan<vlan_id>` stanza with `address`/`vrf` plus an FRR `vrf <name> / vni <l3vni>` block. |
| A3 | A **spine or super-spine** emits the FRR `router bgp` / `address-family l2vpn evpn` block but **no** `bridge` stanza, **no** `vni<N>` stanza, **no** `vrf ... vni ...` block anywhere in the artifact. |
| A4 | `vxlan-local-tunnelip` uses the device's `vtep`-role interface address; FRR `bgp router-id` and `update-source` use the `loopback`-role address — the two are never the same line. |
| A5 | A segment with **no** gateway still gets a `vni<l2vni>` stanza and appears in `bridge-vids`, but **no** `vlan<vlan_id>` stanza. |
| A6 | `route-reflector-client` appears only on sessions with `rr_client` true, and only on devices that have at least one such session. |
| A7 | Uncabled interfaces still get an `iface` stanza with `alias`/`link-down yes` — never omitted, matching the "present but disabled" contract every other vendor already has. |
| A8 | Re-rendering an unchanged device produces byte-identical output (session and VNI iteration order is deterministic). |

## Out of scope for this template

Interface MTU; realistic management (`eth0`) addressing; AAA/NTP/syslog; per-server access-port VLAN
membership (`bridge-ports` listing individual `swpN` members per VLAN) — the template renders the VNI
interfaces and their bridge-vids membership, not the individual tagging commands for every server-facing
port, which is not information the shared query provides per segment (same gap SONiC's contract already
flags for `config vlan member add`); any change to the shared query. **A rendered anycast-gateway MAC on the
leaf SVI** — Arista and Juniper both render one; Cumulus Linux's real equivalent
(`address-virtual <mac> <ip>` under a routed SVI, Cumulus's own anycast-gateway feature) was not confirmed
with enough certainty to render here without guessing, so it is deliberately omitted, matching SONiC's own
SAG omission precedent exactly — flag explicitly for the SC-001 reviewer. **The alternative
`router bgp <asn> vrf <name>` per-VRF BGP-instance EVPN model** some Cumulus reference designs use instead of
the static `vrf/vni/exit-vrf` binding — not rendered; see spec Out of Scope.
