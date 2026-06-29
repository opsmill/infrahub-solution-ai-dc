# Phase 0 Research: EVPN/VXLAN Overlay

All design questions were resolved in a prior grilling session (decisions **D1–D14**); rationale also lives
in `docs/adr/0001`–`0004`. This file consolidates them in Decision / Rationale / Alternatives form, plus the
Infrahub SDK and GraphQL mechanics validated against the codebase. **No blocking `NEEDS CLARIFICATION`
remain.**

## Architecture & control plane

### D1 — Overlay scope is per-fabric
- **Decision**: A Tenant and its VRFs/Segments belong to exactly one Fabric; each Fabric is an independent
  EVPN domain with its own ASN and VNI/RT space.
- **Rationale**: Two independent Clos fabrics; fabric-local numbering is simplest and collision-free.
- **Alternatives**: Cross-fabric tenants (rejected — requires DCI: inter-fabric gateways, RT stitching).

### D2 — Standalone OverlayGenerator beside the physical cascade
- **Decision**: Tenant is a first-class design object with a dedicated OverlayGenerator (triggered by
  `NetworkTenant` checksum); physical generators get only small device-attribute extensions.
- **Rationale**: Tenancy is orthogonal to the physical hierarchy and has its own lifecycle; preserves
  "one generator owns one concern" and a scoped day-two workflow (symmetric with add-rack).
- **Alternatives**: Fold overlay into the Rack generator (rejected — conflates lifecycles, forces rebuilds).

### D3 — Hierarchical route reflection, leaf-only VTEPs
- **Decision**: leafs = RR clients of their spines; spines = RR for leafs **and** clients of super-spines;
  super-spines = top RR. Only leafs are VTEPs.
- **Rationale**: Canonical 5-stage design; sessions follow topology; low per-leaf session count.
- **Alternatives**: Super-spines-only RR (rejected — more sessions/leaf, spine tier carries no EVPN).

### D8 — ASN from a global NumberPool, stamped to devices
- **Decision**: A global `CoreNumberPool` → `NetworkFabric.overlay_asn`; FabricGenerator stamps
  `device.asn = overlay_asn`. Template renders `router bgp {{ device.asn }}`.
- **Rationale**: ASN-as-allocated-resource fits the Resource Manager showcase; control-plane-agnostic value
  line eases the eBGP switch (only neighbor remote-as logic + pool change differ).
- **Alternatives**: Operator-set fabric attribute (workable but less RM-showcase); per-device pool now
  (deferred to eBGP — D13/extensibility).

## Services & data model

### D5 — Anycast gateway optional on Segment
- **Decision**: Segment is always an L2VNI bridge; subnet + anycast gateway are optional (present ⇒ IRB,
  absent ⇒ L2-only). Segment always nests under a VRF.
- **Rationale**: Near-free flexibility; reflects real tenants with mixed routed/bridge-only segments.
- **Alternatives**: Always-IRB (rejected — no L2-only support).

### D7 — VLAN-based service model, fabric-global VLANs
- **Decision**: 1 VLAN ↔ 1 L2VNI ↔ 1 Segment; NX-OS `feature vn-segment-vlan-based`; VLAN ID is a
  fabric-consistent handle, L2VNI is the global id.
- **Alternatives**: VLAN-aware bundle / multi-VLAN EVI (rejected — unnecessary complexity for the demo).

### D13 — Schema shape & simplifications
- **Decision**: Tenant/VRF/Segment are plain `Network`-namespace nodes with `kind: Parent` relationships
  (not `NetworkBuildingBlock`). **No `route_reflector` boolean** (derived from tier ordering in the template).
  Materialize **only `Device↔Segment`** (VRF presence derived via `segment.vrf`).
- **Rationale**: Different kinds → plain parent rels; tier ordering is the cleaner RR source and also right
  for eBGP-future; one materialized relationship is enough.

### D14 — L3VNI transit VLAN + two VLAN pools
- **Decision**: Add `NetworkVrf.l3_vlan_id` for the L3VNI transit/core SVI. Two VLAN pools over disjoint
  ranges: L2 `100–3899` → `Segment.vlan_id`, L3 `3900–4094` → `Vrf.l3_vlan_id`.
- **Rationale**: Symmetric IRB needs a transit VLAN per VRF on each carrying leaf; a NumberPool binds to one
  (node, attribute), so two pools are required.
- **Alternatives**: Deterministic L3 VLAN derivation (rejected — reintroduces collision risk).

## Allocation, addressing, placement, triggering

### D6 — VLAN/L2VNI/L3VNI from per-fabric NumberPools
- **Decision**: NumberPools (Resource Manager), not deterministic compute. Ranges: VLAN-L2 100–3899,
  VLAN-L3 3900–4094, L2VNI 10000–19999, L3VNI 50000–59999.
- **Rationale**: On-brand with the solution's RM teaching point; queryable, collision-free.
- **Alternatives**: `VNI = base + VLAN` (noted as the simpler documented alternative).

### D9 — RT stored (generator-set, queryable); RD template-rendered
- **Decision**: OverlayGenerator stores `route_target = "<asn>:<vni>"` on VRF/Segment; RD is per-device →
  rendered in template `<loopback0>:<id>`. Optional `import_rt`/`export_rt` overrides reserved.
- **Rationale**: Queryable source of truth without computed-attr relationship-traversal risk; RD has no
  single home object.
- **Alternatives**: Computed-attribute RT (traversal uncertain); NX-OS `auto` (hides RD/RT from Infrahub).

### D10 — Separate overlay supernet; default IP namespace first
- **Decision**: New IPPrefix roles `overlay_supernet` + `tenant_subnet`; segment subnets from an overlay
  supernet distinct from underlay `10.0.0.0/8`. Anycast GW = `.1`, distributed; fabric-wide
  `anycast-gateway-mac` (template constant + optional Fabric override). Default namespace initially;
  optional `ip_namespace` on VRF/Tenant reserved for overlapping tenant space.
- **Alternatives**: Per-VRF namespaces now (deferred — heavier generator bookkeeping for a phase-2 toggle).

### D4 — Dedicated VTEP loopback1 on leafs
- **Decision**: Leaf loopback1 (role `vtep`) as NVE source; advertised in OSPF; allocated from a per-pod
  VTEP pool (role `pod_vtep_loopback`). loopback0 stays router-id/iBGP source. Spines/super-spines: none.
- **Rationale**: Standard best practice; keeps anycast-VTEP/MLAG open; role-based IPAM consistency.

### D11/D12 — Placement (advertise-all default) via materialized relationship (Design Y)
- **Decision**: Optional `Segment↔Rack` placement intent (empty ⇒ every leaf in fabric). OverlayGenerator
  materializes `Device↔Segment` onto carrying leafs; leaf-device change rides the existing
  device→artifact regeneration path.
- **Rationale**: Reuses the established checksum cascade; simple per-device transform query (`device.segments`).
- **Alternatives**: Render-time filtering + group artifact-regen trigger (rejected — less-proven action,
  pushes placement logic into the template).
- **Caveat**: Exclude overlay relationships from Rack/Pod generator checksums to avoid a re-trigger loop.

## Validated Infrahub SDK / GraphQL mechanics

- **NumberPool**: no `allocate_next_number()` SDK method. `CoreNumberPool` binds to one (node, attribute);
  allocation is server-side via `from_pool` (pass the pool to the Number attribute on create, like the
  existing IP pools). **Allocated values are not readable on the returned node — re-fetch with `client.get()`**
  (the repo's generators already do this; see their "FIX" comments).
- **IP namespaces**: namespace is a property of the **pool** (`ip_namespace=...`) and the prefix, not a
  parameter of `allocate_next_ip_prefix/address`; the `identifier` arg is idempotency only.
- **GraphQL endpoints traversal (RESOLVED)**: `transforms/computed_interface_description.gql:16` already uses
  `... on NetworkInterface { device { node {...} } }` over `link → endpoints`. So iBGP peer-loopback
  discovery is: `interfaces → link → endpoints → ... on NetworkInterface → device → node → { role, loopback_ip }`.
  In this Clos, iBGP peers are exactly the directly-cabled neighbors.

## Open items to verify during implementation (non-blocking)

1. `from_pool` idempotency on a Number attribute across generator re-runs (guard `overlay_asn` allocation
   with "only if unset"); whether `infrahubctl object load` supports `from_pool` for a Number attribute.
2. Deployed task-worker SDK version (pyproject 1.16.0 vs venv 1.22.0) — confirm `CoreNumberPool` behavior.
3. Exact NX-OS rendering details (e.g. `suppress-arp`, `ip forward`, anycast-gateway-mac) against the target
   NOS behavior — config-style only; does not affect the data model.
