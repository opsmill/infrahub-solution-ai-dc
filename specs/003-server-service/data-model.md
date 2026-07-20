# Phase 1 Data Model: Connect L2/L3 Servers to Leaves

Infrahub schema design. New nodes live in `schemas/server.yml`; the BGP-peer generic goes in
`schemas/routing.yml`; other edits target existing schema files. Regenerate
`src/infrahub_solution_ai_dc/protocols.py` after schema changes. All nodes are `Network` namespace unless
noted. Naming and relationship-kind conventions follow the existing overlay/routing schemas.

## New generic (`schemas/routing.yml`)

### NetworkBGPPeer

Common BGP-endpoint identity so a `NetworkBGPSession` can point at either a device or a server (SD3).

| Attribute | Kind | Notes |
|-----------|------|-------|
| `hostname` | Text | shared display/identity handle (matches `NetworkDevice.hostname`) |

| Relationship | Peer | Card. | Kind | Notes |
|--------------|------|-------|------|-------|
| `bgp_sessions` | NetworkBGPSession | many | Component | back-relationship; `identifier: "device__bgp_session"` (reuse existing) |

`NetworkDevice` and `NetworkServer` both `inherit_from: [NetworkBGPPeer]`. (NetworkDevice already has
`hostname` and `bgp_sessions` — the generic formalizes them.)

## New nodes (`schemas/server.yml`)

### NetworkServerService

The design object — the *request* to connect a server. `inherit_from: [GeneratorTarget]` (its `checksum`
drives the ServerGenerator; the checksum must cover its type/VRF/placement/Segment). Owned by the operator;
joins the `server_services` group.

| Attribute | Kind | Notes |
|-----------|------|-------|
| `name` | Text | unique; `human_friendly_id`/`display_label` |
| `layer` | Dropdown | choices `l2`, `l3`; required — the L2/L3 selector |

| Relationship | Peer | Card. | Kind | Notes |
|--------------|------|-------|------|-------|
| `vrf` | NetworkVrf | one | Attribute | **required** (Tenant implied via `vrf.tenant.fabric`) — FR-007 |
| `rack` | LocationRack | one | Attribute | **optional** explicit placement; honored-or-fail (FR-004) |
| `leaf_interface` | NetworkInterface | one | Attribute | **optional** explicit leaf port; single-homed v1 |
| `segment` | NetworkSegment | one | Attribute | **required for L2**, forbidden for L3 (contradiction → invalid) |
| `server` | NetworkServer | one | Attribute | **generator-set** — the materialized implementation object |

Validation (generator-enforced, fail-loud): `layer == l2` ⇒ `segment` required and `segment.vrf == vrf`;
`layer == l3` ⇒ `segment` must be empty (contradictory L3+Segment rejected).

### NetworkServer

The implementation object produced by the generator. **Does NOT inherit `CoreArtifactTarget`** (never in
`devices`/`{vendor}_devices`, never a startup-config artifact). `inherit_from: [NetworkBGPPeer]` so it can be
an eBGP session endpoint (SD3).

| Attribute | Kind | Notes |
|-----------|------|-------|
| `hostname` | Text | unique (from `NetworkBGPPeer`); the server name |
| `layer` | Dropdown | `l2`/`l3`; copied from the service (render/query convenience) |
| `asn` | Number | **optional**; L3 only — allocated from the global Server ASN pool (SD6) |

| Relationship | Peer | Card. | Kind | Notes |
|--------------|------|-------|------|-------|
| `interfaces` | NetworkInterface | many | Component | server-owned ports; `identifier: "server__interface"` |
| `rack` | LocationRack | one | Attribute | resolved placement (chosen or explicit) |
| `bgp_sessions` | NetworkBGPSession | many | Component | inherited; server side of the eBGP pair (L3) |

## Edits to existing nodes

### NetworkBGPSession (`schemas/routing.yml`)

| Relationship | Was | Now | Notes |
|--------------|-----|-----|-------|
| `device` | `peer: NetworkDevice` (Parent) | `peer: NetworkBGPPeer` (Parent) | owning side; unchanged identifier |
| `peer_device` | `peer: NetworkDevice` (Attribute) | `peer: NetworkBGPPeer` (Attribute) | the neighbor (device or server) |

No attribute changes — `address_family` already offers `ipv4_unicast`; `rr_client` already exists. Server↔leaf
sessions: `address_family: ipv4_unicast`, `rr_client: false`, `local_as`/`remote_as` per side (eBGP).

### NetworkInterface (`schemas/device.yml`)

| Change | Notes |
|--------|-------|
| `device` relationship → **optional** | server ports have no owning device (SD4) |
| **NEW** `server` relationship | peer `NetworkServer`, cardinality one, `kind: Parent`, optional, `identifier: "server__interface"` (back-rel `NetworkServer.interfaces`) |
| `uniqueness_constraints` | widen `[[device, name__value]]` to also key on the server owner so `(server, name)` is unique |

`role` already includes `server` (used for both the leaf-facing port and the server's own port). No new role.

### IpamIPPrefix (`schemas/ipam.yml`)

- Add `server_p2p` to the `role` dropdown (the per-server /31 point-to-point prefix).

### NetworkPod (`schemas/logical_design.yml`)

| New relationship | Peer | Card. | Kind | Notes |
|------------------|------|-------|------|-------|
| `server_prefix_pool` | CoreIPPrefixPool | one | Attribute | optional; mirrors `prefix_pool`/`vtep_pool`; created + attached by `PodGenerator.allocate_resource_pools()` (SD6) |

## Resource pools (object data)

| Pool | Type | Binds to / allocated by | Range / source |
|------|------|-------------------------|----------------|
| Server ASN (global) | CoreNumberPool | `NetworkServer.asn` | **32-bit private** 4200000000–4294967294 (`objects/07_pools.yml`) — distinct from the 64512–65534 overlay ASN range |
| Server /31 (per-Pod) | CoreIPPrefixPool | allocated by ServerGenerator from the pod's `server_prefix_pool` | from a `server_p2p` supernet seeded in `objects/04_ipam.yml`, carved per-Pod by `PodGenerator` |

## Validation rules & derivations

- **VRF required**: a service without `vrf` is invalid (FR-007). Tenant/Fabric are reached via
  `vrf.tenant.fabric` (per-fabric scope of racks/leaves).
- **L2 vs L3** (mutually exclusive intents):
  - L2 ⇒ `segment` required, `segment.vrf == service.vrf` (else fail loud); no `asn`, no /31, no session.
  - L3 ⇒ `segment` must be empty; allocate `asn` (if unset), allocate /31, upsert paired eBGP sessions.
- **Placement**: `rack` empty ⇒ least-utilized eligible rack in the Fabric (fewest attached servers),
  deterministic tie-break by rack `index`; `leaf_interface` empty ⇒ lowest free leaf port with `role:server`.
  Explicit values honored exactly; invalid ⇒ fail loud, no partial objects (FR-002/003/004, SC-002).
- **eBGP pairing**: leaf session `remote_as = server.asn`; server session `remote_as = leaf.asn`
  (= fabric overlay ASN). Both `address_family: ipv4_unicast`, `rr_client: false`. Neighbor address = the
  /31 host on the far side (not a loopback).
- **Idempotency** (SC-003): server named deterministically from the service; sessions upserted by
  `"{a}__{b}"` name; /31 allocated by stable `identifier`; ASN allocated only if unset; placement via
  edge-scoped `add_relationships`. Re-run ⇒ empty diff.
- **No re-trigger loop**: server writes onto a leaf (the leaf-side session + server port cabling) and any
  `Segment.racks` change must be **excluded** from Rack/Pod generator checksums (ADR-0004 caveat).

## Entity relationship summary

```text
NetworkServerService (GeneratorTarget)
  ├─ vrf  → NetworkVrf (required)            [→ tenant → fabric = scope]
  ├─ rack → LocationRack (optional, explicit)
  ├─ leaf_interface → NetworkInterface (optional, explicit)
  ├─ segment → NetworkSegment (L2 only)      [generator adds chosen rack to Segment.racks]
  └─ server → NetworkServer (generator-set)

NetworkServer (inherit NetworkBGPPeer; NOT CoreArtifactTarget)
  ├─ interfaces → NetworkInterface (server__interface)   ── cabled via NetworkLink ── leaf NetworkInterface(role:server)
  ├─ rack → LocationRack
  ├─ asn (L3; from global Server ASN pool)
  └─ bgp_sessions → NetworkBGPSession  (L3: server side of the pair)

NetworkBGPSession.device / .peer_device  → NetworkBGPPeer  (NetworkDevice | NetworkServer)
  L3 server↔leaf: address_family=ipv4_unicast, rr_client=false, eBGP remote_as per side, neighbor over /31

leaf NetworkInterface(role:server) 0..1── IpamIPAddress (rack-side /31 host, role server_p2p)
NetworkPod 0..1── server_prefix_pool (CoreIPPrefixPool)
```
