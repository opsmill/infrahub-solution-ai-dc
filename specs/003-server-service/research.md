# Phase 0 Research: Connect L2/L3 Servers to Leaves

Design decisions **SD1–SD11** (Decision / Rationale / Alternatives) plus the Infrahub SDK & GraphQL mechanics
validated against the current codebase. Most decisions were pinned in the issue-#51 grilling session; this
file grounds them in the real schema/source and resolves the open modeling questions. **No blocking
`NEEDS CLARIFICATION` remain** — a small number of non-blocking implementation-verify items are listed at
the end.

## Data model & split

### SD1 — Two-node design/implementation split

- **Decision**: `NetworkServerService` (the *request* — L2/L3, VRF, optional Rack/leaf-port, optional
  Segment; `inherit_from: [GeneratorTarget]`) is separate from `NetworkServer` (the *implementation* — the
  concrete server + interfaces). Both live in a new `schemas/server.yml`.
- **Rationale**: Mirrors the Tenant→overlay split (ADR-0002) and the whole solution's design-vs-impl
  principle; the service is the trigger target, the server is generator-owned state.
- **Alternatives**: One combined node (rejected — conflates operator intent with materialized state, breaks
  idempotency reasoning).

### SD2 — Standalone ServerGenerator, checksum-triggered

- **Decision**: A dedicated `ServerGenerator` targets a new `server_services` group and is triggered by
  `NetworkServerService` checksum (like the OverlayGenerator). It stamps its own content-hash `checksum`
  via an `update_checksum` step and uses `save(allow_upsert=True, update_group_context=False)` for all
  mutations, plus edge-scoped `add_relationships`/`remove_relationships` for placement.
- **Rationale**: "One generator owns one concern" (ADR-0002); server attachment is orthogonal to fabric
  build and has its own day-two lifecycle; `update_group_context=False` prevents pruning operator-owned
  nodes (the pattern already used in `generate_tenant.py`).
- **Alternatives**: Fold into the Rack generator (rejected — conflates lifecycles, forces rack rebuilds).

## BGP & sessions

### SD3 — Generalized `NetworkBGPPeer`; server↔leaf eBGP is `ipv4_unicast`

- **Decision**: Introduce a `NetworkBGPPeer` generic (namespace `Network`). Both `NetworkDevice` and
  `NetworkServer` `inherit_from` it, and it owns the `bgp_sessions` back-relationship. Repoint
  `NetworkBGPSession.device` and `.peer_device` from `peer: NetworkDevice` to `peer: NetworkBGPPeer`.
  Server↔leaf sessions use `address_family: ipv4_unicast` (**already a valid choice** in `routing.yml`),
  `rr_client: false`, `local_as`/`remote_as` = each side's own/peer ASN. Two sessions per adjacency (one
  each direction), created by a new `servers.upsert_ebgp_session(...)` helper modeled on
  `overlay.upsert_evpn_session(...)`.
- **Rationale**: The existing session model (ADR-0005) is directional and already the fabric's source of
  truth; generalizing the peer is the minimal change that lets a server be a session endpoint. `ipv4_unicast`
  already exists — no new enum. The paired-both-directions upsert is proven in `generate_rack.py`/
  `generate_pod.py`.
- **Alternatives**: A server-specific session node (rejected — duplicates the model, splits the source of
  truth); render-time derivation (rejected — ADR-0005 already moved away from that).
- **Note**: The server-side session is stored for queryability/completeness (FR-005) but is **not** rendered
  anywhere in this repo — server-side OS config is out of scope. Only the leaf side reaches a template.

### SD4 — Server ports reuse `NetworkInterface` via an optional owner

- **Decision**: The server's own port is a `NetworkInterface`. Add an optional `server` owner relationship
  on `NetworkInterface` (peer `NetworkServer`, back-relationship `NetworkServer.interfaces`, `kind: Parent`)
  and make the existing `device` relationship **optional**; widen the uniqueness constraint to cover the
  server owner. The leaf-side server-facing port is an **existing** leaf `NetworkInterface` with
  `role: server` (already produced by the interface profiles/templates).
- **Rationale**: Reuses the cabling model — `NetworkLink.endpoints` is a `NetworkEndpoint` generic
  (`max_count: 2`) and `NetworkInterface` already inherits it — so a server port cables to a leaf port with
  no new link type. An optional owner is less invasive than a full owner-generic refactor.
- **Alternatives**: A separate `NetworkServerInterface` kind (rejected — a parallel interface model the
  cabling/addressing helpers would have to special-case); generalize `device` to a host generic (rejected —
  wider blast radius across existing device queries/transform). **Verify** existing queries tolerate a null
  `device`.

## Placement, ports, allocation

### SD5 — Least-utilized rack + lowest free `server` port; honor-or-fail

- **Decision**: When no Rack is given, pick the **least-utilized eligible Rack** in the VRF's Fabric
  (fewest attached servers), deterministic tie-break by Rack `index`/name — a **pure function** in
  `servers.py`, unit-tested like `resolve_segment_devices`. When no port is given, pick the **lowest free
  leaf `NetworkInterface` with `role == "server"`** (`client.filters(kind=NetworkInterface,
  device__ids=[leaf], role__value="server")` minus already-cabled). Explicit Rack/port is honored exactly;
  invalid input (no free port, port taken/wrong-role, rack not in Fabric) → **fail loud** (`ValueError`,
  `vendors.py` convention) producing **no partial objects**.
- **Rationale**: SC-005 (even spread) and FR-002/003/004; mirrors `generate_rack.py`'s
  `filters(role__value="spine")` port discovery and the fail-loud style already in `vendors.py`/
  `generate_rack.py`.
- **Alternatives**: Round-robin / random placement (rejected — not deterministic, not testable);
  silent reallocation on invalid input (rejected — FR-004/SC-002 require fail-loud).

### SD6 — Pools: per-Pod /31 prefix pool; **global** server-ASN NumberPool

- **Decision**:
  - **/31 pool** — a per-Pod `CoreIPPrefixPool` (role `server_p2p`), created and attached by
    `PodGenerator.allocate_resource_pools()` exactly like the existing `prefix_pool`/`vtep_pool`; new
    `NetworkPod.server_prefix_pool` relationship. The ServerGenerator allocates the /31 from the leaf's
    pod's pool.
  - **Server ASN** — a **single global** `CoreNumberPool` ("Server ASN Pool") bound to `NetworkServer.asn`
    over a **32-bit private ASN range (4200000000–4294967294)**, in `objects/07_pools.yml`.
- **Rationale**: `CoreIPPrefixPool` is allocated by passing the explicit pool object, so per-Pod scoping is
  natural (and matches the PRD's "Pod gains a server /31 pool"). A `CoreNumberPool` binds to exactly one
  (node, attribute), so a *per-Pod* server-ASN pool would mean many pools contending for the same
  `NetworkServer.asn` attribute; a single global pool is collision-free, matches the existing
  `Overlay ASN Pool` pattern, and a 32-bit private range avoids overlap with the 16-bit overlay ASN range
  (64512–65534) used for the iBGP fabric — which is required anyway because server↔leaf is **eBGP** (server
  ASN ≠ leaf/fabric ASN).
- **Deviation from PRD**: The PRD listed the server-ASN pool as a Pod-level pool. This refines it to a
  global NumberPool for the reason above; the /31 pool stays per-Pod as written.
- **Alternatives**: Per-Pod NumberPools (rejected — (node, attribute) binding conflict, and ASNs need only
  be unique per eBGP peering, which a global pool guarantees); deriving ASN arithmetically (rejected — the
  PRD wants Resource-Manager allocation, on-brand with the solution).

### SD7 — /31 addressing via the existing p2p helper; `server_p2p` IPAM role

- **Decision**: Add `server_p2p` to `IpamIPPrefix.role`. Allocate the /31 and assign both host addresses via
  the existing `addressing.assign_ip_addresses_to_p2p_connections(..., prefix_len=31,
  prefix_role="server_p2p", pool=<pod server_prefix_pool>)` — the leaf gets the rack-side address, the
  server gets the other. `IpamIPAddress` has no roles, so no edit there.
- **Rationale**: Directly reuses the helper the rack generator already uses for leaf↔spine /31s; role-based
  IPAM consistency.
- **Alternatives**: Hand-rolled /31 math in the generator (rejected — duplicates a tested helper).

## L2 path & triggering

### SD8 — L2 attaches the leaf's Rack to `Segment.racks`; no BGP/IP

- **Decision**: For L2, resolve the Segment under the service's VRF (fail loud if the Segment's `vrf` ≠ the
  service's VRF), then **idempotently add the chosen leaf's Rack to `NetworkSegment.racks`** via
  `add_relationships("racks", [...])`. Create **no** BGP session and **no** fabric-side IP.
- **Rationale**: `NetworkSegment.racks` is the existing placement intent (ADR-0004); the OverlayGenerator's
  materialization path then carries the segment onto the rack's leaves. FR-006/US2.
- **Open interaction (verify, non-blocking)**: Adding a Rack to `Segment.racks` does not by itself bump the
  owning `NetworkTenant` checksum, so the OverlayGenerator may not auto-re-run to materialize
  `Device↔Segment`. Options: (a) leave overlay materialization as a separate operator/trigger step (the L2
  acceptance only asserts the placement grew + no BGP/IP), or (b) add a `CoreNodeTriggerRule` on
  `NetworkSegment.racks` → `run-tenant-generator`. Recommend (a) for v1, note (b) as a follow-up. Either way
  overlay relationships stay **excluded** from Rack/Pod checksums (ADR-0004 caveat).
- **Alternatives**: Directly materialize `Device↔Segment` from the server generator (rejected — that is the
  OverlayGenerator's concern; would duplicate placement logic and risk double-ownership).

### SD9 — Template: server-port + eBGP `ipv4_unicast` branches (leaf only)

- **Decision**: In each `startup_config_{cisco,arista,dell}.j2`, add (1) a `role == "server"` interface
  branch that renders the port as routed with its /31 (`no switchport` + `ip address <\/31>`), and (2) an
  eBGP neighbor branch keyed on `session.address_family == "ipv4_unicast"`: neighbor peered over the **/31
  address** (not a loopback), `remote-as <session.remote_as>`, **no** `update-source Loopback0`, **no**
  `route-reflector-client`, activated under the ipv4-unicast address-family (not `evpn`). `startup_config.gql`
  additionally selects `address_family`, `local_as`, and the peer/interface /31 address on `bgp_sessions`.
- **Rationale**: FR-009/SC-004; the current template renders only `l2vpn_evpn` sessions over loopbacks and
  ignores `role == "server"` ports and `address_family`. Only the leaf renders (the server has no artifact).
- **Alternatives**: A separate server-config artifact (rejected — server-side config out of scope).

## Registration, seed, tests

### SD10 — Registration & trigger mirror the tenant generator

- **Decision**: `.infrahub.yml` gains a `generate_server` query and a `generate-server`
  `generator_definition` (`class_name: ServerGenerator`, `targets: server_services`,
  `convert_query_response: false`, `execute_in_proposed_change/after_merge: false`). `objects/01_groups.yml`
  gains a `server_services` `CoreStandardGroup`. `triggers.yml` gains a `CoreGeneratorAction`
  (`run-server-generator` → `generate-server`) and a `CoreNodeTriggerRule` on `NetworkServerService`
  `updated`/checksum. Menu entry optional.
- **Rationale**: Exactly the tenant generator's registration shape; `NetworkServer` is deliberately kept out
  of `devices`/`{vendor}_devices` so no artifact is produced for it.

### SD11 — Seed object + tests

- **Decision**: Seed one L3 (Cilium) `NetworkServerService` in a new `objects/13_servers.yml`. Unit tests
  (`tests/unit/test_servers.py`) cover the pure helpers (least-utilized rack + tie-break, port selection,
  server-ASN/pool lookup, /31 pairing → correct remote-AS each side) and every fail-loud path
  (no eligible rack/port, invalid explicit placement, Segment-not-in-VRF, pool exhaustion, contradictory
  L3+Segment). An integration test (`tests/integration/test_server_service.py`) covers the L2, L3, and
  explicit-placement journeys end-to-end plus an idempotent re-run (empty diff), mirroring
  `tests/integration/test_overlay_daytwo.py`.
- **Rationale**: Matches the existing test taxonomy; tests assert external behaviour (materialized objects +
  fail-loud paths), not internal allocation, per the spec's testing intent.

## Validated Infrahub SDK / GraphQL mechanics

- **NumberPool**: no `allocate_next_number()`; a `CoreNumberPool` binds one (node, attribute) and allocation
  is server-side via `from_pool` — assign the pool object to the Number attribute and save. **Allocated
  values are not readable on the returned node → re-fetch with `client.get()`** (the generators already do
  this; see `generate_tenant.py` re-fetch idiom).
- **IPPrefix pools**: `client.allocate_next_ip_prefix(resource_pool=pool, identifier=<stable id>,
  member_type="address", prefix_length=31, data={"role": "server_p2p"})`; `identifier` is idempotency only.
  Per-Pod pools created in `PodGenerator.allocate_resource_pools()` via `client.create(kind=CoreIPPrefixPool,
  ...)` from a parent supernet, then attached (`pod.server_prefix_pool = ...; pod.save()`).
- **Paired session upsert**: `overlay.upsert_evpn_session(client, logger, device, peer, asn,
  peer_is_rr_client=...)` creates `NetworkBGPSession` named `"{device}__{peer}"` and
  `save(allow_upsert=True)`. The server helper follows this shape with `address_family="ipv4_unicast"`,
  distinct `local_as`/`remote_as`, `rr_client=False`, one call per direction.
- **Cabling**: `NetworkLink.endpoints` (generic `NetworkEndpoint`, `max_count: 2`); reuse the rack
  generator's interface-map/`connect_interface_maps` flow to cable server↔leaf.
- **Query model convention**: two files — `generate_server.gql` (nested `edges { node { ... } }`, inline
  fragments like `... on NetworkFabric`) + a hand-written `generate_server_query.py` pydantic model
  (`_Value*` leaf models, `_`-prefixed privates, `Field(alias="NetworkServerService")`), with
  `convert_query_response: false`.
- **Fail-loud convention** (`vendors.py`): `msg = f"...{offending_label}..."; raise ValueError(msg)` (assign
  to a local first for ruff EM102); generators use `RuntimeError` for "not fully generated yet".

## Open items to verify during implementation (non-blocking)

1. `from_pool` on a **new** `NetworkServer.asn` Number attribute, guarded "allocate only if unset"; confirm
   a global `CoreNumberPool` on that attribute allocates cleanly and is re-fetchable (SD6).
2. Repointing `NetworkBGPSession.device`/`peer_device` to the `NetworkBGPPeer` generic — regenerate
   `protocols.py` and confirm `overlay.upsert_evpn_session` and the startup-config query still resolve (SD3).
3. `NetworkInterface.device` made optional + new `server` owner + widened uniqueness constraint — confirm
   existing interface queries/transform tolerate a null `device` (SD4).
4. Whether to auto-re-trigger the OverlayGenerator on a `Segment.racks` change for the L2 path, or keep it a
   separate step (SD8) — decide during implementation; v1 default is the separate step.
5. Exact per-NOS rendering of the routed server port + eBGP neighbor for cisco/arista/dell (config style
   only; does not affect the data model) (SD9).
