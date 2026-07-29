# Contract: Leaf Startup-Config Artifact

What the per-vendor startup-config templates
(`transforms/templates/startup_config_{cisco,arista,dell,juniper}.j2`) must render for a leaf that has a
server attached. Only the **leaf** renders — `NetworkServer` produces no
artifact. This governs FR-009 and SC-004. The current template already renders OSPF underlay, iBGP
L2VPN-EVPN neighbors (over loopbacks), and NVE/VLAN/VRF/SVI for overlay segments; this contract adds two
branches.

## 1. Server-facing interface (both L2 and L3, but IP only for L3)

For a leaf `NetworkInterface` with `role == "server"` that is cabled to a server:

- **L3**: render as a **routed** port — `no switchport` (arista/dell idiom; cisco `no switchport` under the
  interface) and `ip address <rack-side /31>` from the interface's `ip_address` (role `server_p2p`), plus
  `no shutdown` when `status == active`. Junos has no `no switchport`: the port is routed by giving its
  `unit 0` a `family inet { address <rack-side /31>; }` instead of `family ethernet-switching`.
- **L2**: render as an access/switched port in the segment's VLAN (no IP) — on Junos, `unit 0` keeps
  `family ethernet-switching`. (Reuses the existing switched-port rendering; the segment reaches the leaf
  via the overlay `Device↔Segment` materialization, not this feature.)

The presence of an `ip_address` on the port is what selects routed vs bridged, since the template sees the
interface and not the service's `layer`.

The current `role == "server"` interfaces render neither `no switchport` nor an IP — that gap is what this
branch fixes.

## 2. eBGP `ipv4_unicast` neighbor (L3 only)

Iterating `device.bgp_sessions` (already sorted by peer hostname), branch on `session.address_family`:

- `l2vpn_evpn` → **existing** behaviour: neighbor at `peer_device.loopback_ip`, `update-source Loopback0`,
  `send-community extended`, `route-reflector-client` iff `rr_client`, activated under `address-family evpn`.
- `ipv4_unicast` → **new** behaviour, for the server peer:
  - `neighbor <far-side /31 address> remote-as <session.remote_as>` — the neighbor address is the **server's
    interface /31 host** (via the `... on NetworkServer { interfaces … ip_address }` query fragment), **not**
    a loopback.
  - **No** `update-source Loopback0` (peering is over the directly-connected /31).
  - **No** `route-reflector-client` (`rr_client` is false for server sessions).
  - Activate under the **ipv4-unicast** address family, not `evpn`.
  - `remote_as` is the server's private ASN (the leaf-side session); the reverse (server-side) session is
    stored but not rendered here.

On Junos the two families are separate BGP groups rather than per-neighbor address families: the existing
`group EVPN-OVERLAY` (`type internal`) must **exclude** `ipv4_unicast` sessions, and a `group SERVER-EBGP`
(`type external`, `family inet { unicast; }`) carries one `neighbor <far-side /31> { peer-as … }` per
attached server. Excluding them from the EVPN group is required, not tidiness: that group dereferences
`peer_device.loopback_ip`, which the query exposes only `... on NetworkDevice`, so a server session reaching
it fails the whole artifact. The local AS comes from the `routing-options autonomous-system` already
rendered, so the external group needs no `local-as`.

## Acceptance mapping

| Rendered element | Requirement |
|------------------|-------------|
| server interface present with `no switchport` + /31 (L3) | FR-009, SC-004 |
| eBGP `ipv4_unicast` neighbor over the /31, correct remote-as | FR-005, FR-009, SC-004 |
| no server neighbor / IP on an L2 attachment's leaf | FR-006 |
| unrelated leaves' artifacts byte-identical after adding one server | SC-003 |

## Notes

- Deterministic output: sessions already render sorted by peer hostname; the added branch preserves that
  ordering.
- The four vendor templates differ only in NOS syntax; the data they consume (interface role + IP, session
  `address_family`/`remote_as`/far-side address) is identical.
- `objects/13_servers.yml` seeds an L3 + L2 pair on the `Blue` tenant (Fabric-A, Cisco) and on `Green`
  (Fabric-D, Juniper), so a plain `inv load` exercises both NOS dialects of this contract.
