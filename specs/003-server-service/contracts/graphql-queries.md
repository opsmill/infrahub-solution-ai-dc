# Contract: GraphQL Queries

The ServerGenerator and the startup-config transform consume Infrahub via GraphQL. These are the query
contracts (inputs + the shape each must return). Existing `generators/*.gql` / `transforms/*.gql` are the
style reference; the `*_query.py` pydantic models are hand-written per the repo convention (`_Value*` leaf
models, `_`-prefixed privates, `Field(alias=...)`), with `convert_query_response: false`.

## `generators/generate_server.gql` (NEW) — ServerGenerator input

**Input variable**: `$name: String!` (the `NetworkServerService.name`, per the generator_definition
`parameters: {name: name__value}`).

**Must return** (the intent the generator reads, plus what it needs to resolve/allocate against):

```text
NetworkServerService(name__value: $name)
  edges { node {
    id, name, checksum                                   # GeneratorTarget
    layer                                                # l2 | l3
    server { node { id, hostname } }                     # generator-set; null on first run
    rack   { node { id, name, index } }                  # optional explicit placement
    leaf_interface { node { id, name, role,              # optional explicit leaf port
                            device { node { id, hostname, role } } } }
    segment { node { id, name, vrf { node { id } } } }   # L2 only; validate vrf == service.vrf
    vrf { node { id, name
      tenant { node { id, name
        fabric { node { ... on NetworkFabric { id, name, overlay_asn } } } }   # scope + leaf ASN
    } } }
  }}
```

**Generator responsibilities** (from this data):

- Resolve scope: `vrf.tenant.fabric` → the Fabric whose racks/leaves are eligible.
- Placement: honor `rack`/`leaf_interface` if given (fail loud if invalid); else pick least-utilized rack +
  lowest free `role:server` leaf port (queried separately via `client.filters`).
- Materialize `NetworkServer` (+ its `interfaces`), cable server↔leaf (`NetworkLink`), set `service.server`.
- **L3**: allocate `NetworkServer.asn` (global pool, only if unset), allocate a /31 from the leaf pod's
  `server_prefix_pool` (role `server_p2p`), assign both host addresses, upsert the paired eBGP sessions
  (leaf `remote_as = server.asn`; server `remote_as = fabric.overlay_asn`; both `ipv4_unicast`,
  `rr_client: false`).
- **L2**: validate `segment.vrf == vrf`; idempotently add the chosen leaf's Rack to `segment.racks`; create
  no session/IP.
- Stamp the service checksum (`update_checksum`) last.

Separate lookups the generator issues (not in the target query): free `role:server` leaf ports per candidate
leaf (`filters(kind=NetworkInterface, device__ids=[leaf], role__value="server")`), the global
`Server ASN Pool` (`get(CoreNumberPool, name__value=...)`), and the pod's `server_prefix_pool`.

## `transforms/startup_config.gql` (EDIT) — per-device (leaf) config input

Extend the existing `bgp_sessions` block on `NetworkDevice(hostname__value: $name)` so eBGP server sessions
render, and expose the server-facing interface IP.

**Add to `bgp_sessions { edges { node { … } } }`**:

```text
address_family                       # NEW — distinguishes ipv4_unicast (server) from l2vpn_evpn
local_as                             # NEW
peer_device { node {
  hostname
  loopback_ip { node { address { value } } }        # existing — used for l2vpn_evpn
  ... on NetworkServer {                             # NEW — server peer has no loopback
    interfaces { edges { node { ip_address { node { address { value } } } } } }
  }
}}
```

**Add to the existing `interfaces` block** (so the server-facing leaf port renders its /31): ensure each
interface returns `role` and `ip_address { node { address { value } } }` (already present for other roles).

**Notes**:

- The template branches on `address_family`: `l2vpn_evpn` → existing loopback-peered EVPN neighbor;
  `ipv4_unicast` → neighbor peered over the far-side /31 address, `remote-as = remote_as`, no
  `update-source`, no `route-reflector-client`, activated under ipv4-unicast (see `config-artifact.md`).
- Only the **leaf** renders. `NetworkServer` is not a `CoreArtifactTarget`, so no server config query exists.
- The far-side /31 address for a server neighbor comes from the server's own interface IP (the `... on
  NetworkServer` fragment), since the server has no loopback.
