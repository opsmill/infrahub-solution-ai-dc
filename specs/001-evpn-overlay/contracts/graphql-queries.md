# Contract: GraphQL Queries

The generators/transforms consume Infrahub via GraphQL. These are the query contracts (inputs + the shape
of data each must return). Existing queries in `generators/*.gql` and `transforms/*.gql` are the style
reference; the `*_query.py` pydantic models are generated, not hand-written.

## `generators/generate_tenant.gql` (NEW) — OverlayGenerator input

**Input variable**: `$name: String!` (the `NetworkTenant.name`, per the generator_definition parameter).

**Must return** (intent the generator reads, plus what it needs to allocate against):

```text
NetworkTenant(name__value: $name)
  name
  checksum                              # GeneratorTarget
  fabric { node { name, overlay_asn } } # ASN for RT strings; fabric scope
  vrfs { edges { node {
    id, name, l3vni, l3_vlan_id, route_target
    segments { edges { node {
      id, name, vlan_id, l2vni, route_target
      subnet  { node { id, prefix } }   # may be null (L2-only)
      gateway { node { id, address } }  # may be null
      racks   { edges { node { id, name } } }   # placement intent (may be empty → advertise-all)
    }}}
  }}}
```

**Generator responsibilities** (from this data): allocate `l2vni`/`vlan_id` (segments) and `l3vni`/
`l3_vlan_id` (VRFs) from pools (re-fetch to read), allocate `subnet` + `.1` `gateway` for IRB segments,
set `route_target` strings (`<overlay_asn>:<vni>`), and materialize `Device.segments` on the carrying leafs
(resolve `racks` → leafs; empty ⇒ all leafs in `fabric`).

## `transforms/startup_config.gql` (EDIT) — per-device config input

**Input variable**: `$name: String!` (the `NetworkDevice.hostname`).

**Add to the existing query** (keep current hostname/loopback_ip/interfaces blocks):

```text
NetworkDevice(hostname__value: $name)
  role
  asn
  vtep_ip { node { address } }                         # leafs only
  pod { node { parent { ... on NetworkFabric { overlay_asn, anycast_gateway_mac } } } }
  bgp_sessions { edges { node {                           # ADR-0005: sessions modeled as data
    name, remote_as, rr_client
    peer_device { node { hostname, loopback_ip { node { address { ip } } } } }
  }}}
  segments { edges { node {                              # materialized; leafs only
    name, vlan_id, l2vni, route_target
    subnet  { node { prefix } }
    gateway { node { address } }
    vrf { node { name, l3vni, l3_vlan_id, route_target } }
  }}}
```

**Notes**:

- iBGP peers = the device's `bgp_sessions` (populated by the pod/rack generators along the cabling,
  ADR-0005); `route-reflector-client` renders from each session's `rr_client` flag. The template sorts
  sessions by peer hostname for deterministic artifacts.
- Spine/super-spine renders have no `segments` (none materialized) → no NVE/VRF/SVI.
- `vrf` data is reached via `segment.vrf` (no separate Device↔VRF relationship).
