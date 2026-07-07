# Phase 1 Data Model: EVPN/VXLAN Overlay

Infrahub schema design for the overlay. New nodes live in `schemas/overlay.yml`; edits target existing
schema files. All tenancy nodes are plain `Network`-namespace nodes with `kind: Parent` relationships (not
the `NetworkBuildingBlock` generic — D13). Regenerate `src/infrahub_solution_ai_dc/protocols.py` after
schema changes.

## New nodes (`schemas/overlay.yml`)

### NetworkTenant

Owner of overlay services, scoped to one fabric. `inherit_from: [GeneratorTarget]` (checksum drives the
OverlayGenerator; the checksum must cover its VRFs/Segments/placement).

| Attribute | Kind | Notes |
|-----------|------|-------|
| `name` | Text | unique; `human_friendly_id`/`display_label` |

| Relationship | Peer | Card. | Kind | Notes |
|--------------|------|-------|------|-------|
| `fabric` | NetworkFabric | one | Attribute | per-fabric scope (D1); required |
| `vrfs` | NetworkVrf | many | — | children |
| `ip_namespace` | CoreIPNamespace | one | Attribute | optional; **reserved** for future overlapping-tenant space (D10) |

### NetworkVrf

A tenant's L3 routing instance (IP-VRF / L3VNI). Parent = Tenant.

| Attribute | Kind | Notes |
|-----------|------|-------|
| `name` | Text | unique within tenant (uniqueness_constraint `[tenant, name__value]`) |
| `l3vni` | Number | **allocated from L3VNI pool** (50000–59999) |
| `l3_vlan_id` | Number | **allocated from VLAN-L3 pool** (3900–4094); transit/core SVI VLAN (D14) |
| `route_target` | Text | **generator-set** `<asn>:<l3vni>` (D9) |
| `import_rt` | Text | optional manual override (route-leaking); default = `route_target` |
| `export_rt` | Text | optional manual override; default = `route_target` |

| Relationship | Peer | Card. | Kind | Notes |
|--------------|------|-------|------|-------|
| `tenant` | NetworkTenant | one | Parent | required |
| `segments` | NetworkSegment | many | — | children |
| `ip_namespace` | CoreIPNamespace | one | Attribute | optional; reserved (D10) |

### NetworkSegment

A tenant L2 service (MAC-VRF / L2VNI). One VLAN ↔ one L2VNI (D7). Parent = VRF. Optional gateway ⇒ IRB vs
L2-only (D5).

| Attribute | Kind | Notes |
|-----------|------|-------|
| `name` | Text | unique within VRF |
| `vlan_id` | Number | **allocated from VLAN-L2 pool** (100–3899) |
| `l2vni` | Number | **allocated from L2VNI pool** (10000–19999) |
| `route_target` | Text | **generator-set** `<asn>:<l2vni>` (D9) |

| Relationship | Peer | Card. | Kind | Notes |
|--------------|------|-------|------|-------|
| `vrf` | NetworkVrf | one | Parent | required |
| `subnet` | IpamIPPrefix | one | Attribute | **optional**; allocated `tenant_subnet`; present ⇒ IRB |
| `gateway` | IpamIPAddress | one | Attribute | **optional**; anycast SVI virtual IP (`.1` of subnet) |
| `racks` | LocationRack | many | Generic | **optional** placement intent; empty ⇒ advertise-all (D11) |

### NetworkBGPSession (`schemas/routing.yml`, ADR-0005)

A directional iBGP L2VPN-EVPN session from a device toward a peer. Two sessions per cabled adjacency
(one per direction), populated by the pod generator (spine↔super-spine) and the rack generator
(leaf↔spine) along the actual cabling plan. The startup-config transform renders `router bgp` neighbors
from these sessions.

| Attribute | Kind | Notes |
|-----------|------|-------|
| `name` | Text | unique; `<device>__<peer>` (the generators' upsert key) |
| `local_as` | Number | = fabric `overlay_asn` (iBGP); per-device under eBGP later |
| `remote_as` | Number | = fabric `overlay_asn` (iBGP) |
| `address_family` | Dropdown | `l2vpn_evpn` (default), `ipv4_unicast` reserved |
| `rr_client` | Boolean | render `route-reflector-client` toward the peer; **generator-set** from tier ordering |

| Relationship | Peer | Card. | Kind | Notes |
|--------------|------|-------|------|-------|
| `device` | NetworkDevice | one | Parent | owning side (`NetworkDevice.bgp_sessions`) |
| `peer_device` | NetworkDevice | one | Attribute | the neighbor; loopback0 rendered as the neighbor address |

## Edits to existing nodes

### NetworkFabric (`schemas/logical_design.yml`)

| New attribute | Kind | Notes |
|---------------|------|-------|
| `overlay_asn` | Number | optional; **allocated by FabricGenerator from the global ASN pool** (D8) |
| `routing_design` | Dropdown | choices `ibgp_evpn_ospf_underlay` (default), `ebgp_evpn` (reserved — D13/extensibility) |
| `anycast_gateway_mac` | Text | optional override; template constant default (D10) |

### NetworkPod (`schemas/logical_design.yml`)

| New relationship | Peer | Card. | Kind | Notes |
|------------------|------|-------|------|-------|
| `vtep_pool` | CoreIPAddressPool | one | Attribute | optional; mirrors `loopback_pool`; created by PodGenerator (D4) |

### NetworkDevice (`schemas/device.yml`)

| New attribute | Kind | Notes |
|---------------|------|-------|
| `asn` | Number | optional; stamped `= fabric.overlay_asn` (iBGP); per-device unique under eBGP later (D8) |

| New relationship | Peer | Card. | Kind | Notes |
|------------------|------|-------|------|-------|
| `vtep_ip` | IpamIPAddress | one | Attribute | optional; **new** identifier `device__vtep_ip`; leafs only (D4) |
| `segments` | NetworkSegment | many | — | **materialized by OverlayGenerator** (Design Y — D12); leafs only |

**Revised by ADR-0005**: `route_reflector` (Boolean, default false) is stored after all — set true on
spines/super-spines by the fabric/pod generators. It marks the RR role for operators; rendering is driven
by the per-session `rr_client` flag (see NetworkBGPSession below), since a device flag alone cannot
express hierarchical RR (a spine is both reflector and client).

### NetworkInterface (`schemas/device.yml`)

- Add roles to the `role` dropdown: `vtep` (leaf loopback1 / NVE source) and `svi` (anycast gateway + L3
  transit SVIs).

### IpamIPPrefix (`schemas/ipam.yml`)

- Add `role` choices: `pod_vtep_loopback` (per-pod VTEP loopback pool), `overlay_supernet` (tenant address
  space root), `tenant_subnet` (per-segment anycast-gateway subnet).

## Resource pools (object data — `objects/07_pools.yml`, `objects/04_ipam.yml`)

| Pool | Type | Binds to | Range / source |
|------|------|----------|----------------|
| ASN (global) | CoreNumberPool | `NetworkFabric.overlay_asn` | private ASN range |
| L2VNI | CoreNumberPool | `NetworkSegment.l2vni` | 10000–19999 |
| L3VNI | CoreNumberPool | `NetworkVrf.l3vni` | 50000–59999 |
| VLAN-L2 | CoreNumberPool | `NetworkSegment.vlan_id` | 100–3899 |
| VLAN-L3 | CoreNumberPool | `NetworkVrf.l3_vlan_id` | 3900–4094 |
| Tenant subnet | CoreIPPrefixPool | (allocated by OverlayGenerator) | from `overlay_supernet` |
| VTEP loopback (per-pod) | CoreIPAddressPool | (allocated by PodGenerator) | from `pod_vtep_loopback` prefix |

## Validation rules & derivations

- **Uniqueness**: VRF name unique within Tenant; Segment name unique within VRF; all allocated numeric ids
  unique within the fabric (guaranteed by the pools).
- **Gateway implies subnet**: a `gateway` requires a `subnet`; gateway = first usable host (`.1`).
- **Placement → materialization**: `Segment.racks` empty ⇒ every leaf in the Tenant's Fabric; else the leafs
  of the listed racks. OverlayGenerator writes `Device.segments` accordingly.
- **VRF presence on a leaf**: derived — a leaf renders a VRF iff it carries ≥1 of that VRF's segments (via
  `segment.vrf`); a leaf renders a `vrf context` for the distinct VRFs of its **gateway-bearing** segments.
- **RR role**: stored (ADR-0005) — the generators apply tier ordering (super-spine > spine > leaf) once at
  population time, setting `NetworkDevice.route_reflector` and each session's `rr_client`.
- **ASN allocation idempotency**: allocate `overlay_asn` only if unset; exclude `overlay_asn` from the
  fabric checksum to avoid self-retrigger (see research.md open item 1).

## Entity relationship summary

```text
NetworkFabric 1──* NetworkTenant 1──* NetworkVrf 1──* NetworkSegment *──* LocationRack   (placement intent)
                                                              │
NetworkSegment *──* NetworkDevice(leaf)  ← materialized by OverlayGenerator (Design Y)
NetworkSegment 0..1── IpamIPPrefix (subnet) ; 0..1── IpamIPAddress (anycast gateway)
NetworkDevice 0..1── IpamIPAddress (vtep_ip, leafs) ; NetworkDevice.asn = Fabric.overlay_asn
```
