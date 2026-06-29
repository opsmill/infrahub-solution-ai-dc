---
description: "Task list for EVPN/VXLAN Overlay implementation"
---

# Tasks: EVPN/VXLAN Overlay for the AI/DC Fabric

**Input**: Design documents from `/specs/001-evpn-overlay/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md

**Tests**: Test tasks are included because the engineering plan (gap-analysis §8) and the project's
`inv test` workflow call for them. They are targeted unit/integration tasks, not strict TDD-first gates —
implement alongside the code they cover.

**Organization**: Tasks are grouped by user story (US1–US3 from spec.md) for independent implementation and
testing.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: US1/US2/US3 (user-story phases only)
- All paths are repository-relative.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Confirm the working environment; no product code.

- [X] T001 Run `uv sync --all-packages` and confirm work is on branch `wvd-add-overlay`
- [X] T002 [P] Skim implementation references: `CONTEXT.md`, `docs/adr/0001`–`0004`, and `specs/001-evpn-overlay/` (plan/data-model/contracts/quickstart) — no file changes

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The EVPN data model, resource pools, device-level plumbing (ASN + VTEP), and the EVPN
control-plane baseline (BGP sessions + hierarchical RR, no tenant state). **All user stories depend on this.**

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

### Schema & generated types

- [X] T003 [P] Add `NetworkTenant`, `NetworkVrf`, `NetworkSegment` nodes (plain `Network`-namespace, `kind: Parent` rels) in `schemas/overlay.yml` per data-model.md
- [X] T004 [P] Edit `schemas/device.yml`: add `NetworkDevice.asn`, relationship `vtep_ip` (identifier `device__vtep_ip`) and `segments`; add `NetworkInterface` roles `vtep` and `svi`
- [X] T005 [P] Edit `schemas/logical_design.yml`: add `NetworkFabric.overlay_asn`, `routing_design` (default `ibgp_evpn_ospf_underlay`, reserved `ebgp_evpn`), `anycast_gateway_mac`; add `NetworkPod.vtep_pool`
- [X] T006 [P] Edit `schemas/ipam.yml`: add `IpamIPPrefix.role` choices `pod_vtep_loopback`, `overlay_supernet`, `tenant_subnet`
- [X] T007 Regenerate `src/infrahub_solution_ai_dc/protocols.py` from the schema (depends on T003–T006; do not hand-edit)
- [X] T008 Validate schema converges with `inv load-schema` (depends on T007)

### Resource pools, IPAM & groups

- [X] T009 [P] Create `objects/07_pools.yml` with `CoreNumberPool`s: ASN→`NetworkFabric.overlay_asn`, L2VNI→`NetworkSegment.l2vni` (10000–19999), L3VNI→`NetworkVrf.l3vni` (50000–59999), VLAN-L2→`NetworkSegment.vlan_id` (100–3899), VLAN-L3→`NetworkVrf.l3_vlan_id` (3900–4094)
- [X] T010 [P] Edit `objects/04_ipam.yml`: add an `overlay_supernet` prefix + a `CoreIPPrefixPool` allocating `tenant_subnet` prefixes from it
- [X] T011 [P] Add a `tenants` `CoreStandardGroup` to `objects/01_groups.yml`

### Shared helpers

- [X] T012 [P] Add `src/infrahub_solution_ai_dc/overlay.py` with helpers: `route_target(asn, vni)`, `resolve_segment_devices(segment, fabric_leafs)` (placement→leafs; empty⇒all); add a VTEP-loopback assignment helper in `src/infrahub_solution_ai_dc/addressing.py`

### Device-level plumbing (extend physical generators)

- [X] T013 [P] Extend `generators/generate_fabric.py`: allocate `overlay_asn` from the global ASN pool (guard: only if unset; re-fetch to read), default `routing_design`, stamp `asn` on super-spines; **exclude `overlay_asn` from the fabric checksum** (depends on T007, T009)
- [X] T014 [P] Extend `generators/generate_pod.py`: create per-pod VTEP `CoreIPAddressPool` (role `pod_vtep_loopback`) stored on `pod.vtep_pool`; stamp `asn` on spines (depends on T007)
- [X] T015 [P] Extend `generators/generate_rack.py`: assign leaf `vtep_ip` from `pod.vtep_pool`, create + bind a `vtep`-role loopback interface, stamp `asn` on leafs (depends on T007, T012, T014)

### EVPN control-plane baseline (transform — no tenant state yet)

- [X] T016 Extend `transforms/startup_config.gql`: add `role`, `asn`, `vtep_ip`, fabric `overlay_asn`/`anycast_gateway_mac`, and neighbor loopbacks via `interfaces → link → endpoints → ... on NetworkInterface → device { role, loopback_ip }` (per contracts/graphql-queries.md)
- [X] T017 Extend `transforms/templates/startup_config.j2`: advertise the `vtep` loopback in OSPF; add `feature bgp / nv overlay / vn-segment-vlan-based`, `nv overlay evpn`, `router bgp {{ device.asn }}`, iBGP L2VPN-EVPN neighbors to cabled neighbors with `route-reflector-client` derived from tier ordering (super-spine→spine→leaf) — no NVE/VRF/SVI yet (depends on T016)

### UI

- [X] T018 [P] Add a `Network → Overlay` menu group exposing `NetworkTenant`/`NetworkVrf`/`NetworkSegment` in `menus/menu.yml`

**Checkpoint**: Schema loads; an EVPN-ready fabric builds (every device has `asn`, leafs have `vtep_ip`, BGP-EVPN sessions render with hierarchical RR) with **no tenants**; existing underlay/build is unchanged.

---

## Phase 3: User Story 1 - Provision a routed multi-tenant overlay service (Priority: P1) 🎯 MVP

**Goal**: Declare a tenant with a VRF and routed segments → the OverlayGenerator allocates identifiers and
materializes placement, and leaf configs render full symmetric IRB (bridging + inter-subnet routing) while
spines/super-spines carry no tenant state.

**Independent Test**: Seed one tenant (VRF + 2 routed segments), run generation, inspect a leaf artifact
(both segments bridged, local anycast gateway, inter-segment routing) and a spine artifact (EVPN RR, no
tenant state); confirm no identifier was set by hand.

- [X] T019 [P] [US1] Create `generators/generate_tenant.gql` (input `$name`; tenant→fabric/vrfs/segments shape per contracts/graphql-queries.md)
- [X] T020 [US1] Add the `device.segments` (+ `segment.vrf`) block to `transforms/startup_config.gql` (same file as T016; depends on T016)
- [X] T021 [US1] Implement `OverlayGenerator` in `generators/generate_tenant.py`: allocate `l2vni`/`vlan_id` (segments) and `l3vni`/`l3_vlan_id` (VRFs) from pools (re-fetch), allocate `tenant_subnet` + `.1` `gateway` for IRB segments, set `route_target` on VRF/Segment via `overlay.route_target`, materialize `Device.segments` onto carrying leafs (advertise-all) — reuse `GeneratorMixin` checksum (depends on T012, T019)
- [X] T022 [US1] Generate `generators/generate_tenant_query.py` from the `.gql` (depends on T019)
- [X] T023 [US1] Register in `.infrahub.yml`: add `generate_tenant` query + a `generate-tenant` `generator_definition` (target `tenants` group, param `name: name__value`) (depends on T019, T021)
- [X] T024 [US1] Add OverlayGenerator trigger to `objects/20_triggers.yml.save`: `CoreGeneratorAction` `run-tenant-generator` + `CoreNodeTriggerRule` on `NetworkTenant` (checksum + vrfs/segments) (depends on T023)
- [X] T025 [US1] Extend `transforms/templates/startup_config.j2` with leaf tenant rendering: `interface nve1` (source loopback1), per-segment `member vni <l2vni>`/`suppress-arp`, per-VRF `member vni <l3vni> associate-vrf`, `vlan/vn-segment` (L2 + L3 transit), `vrf context` (`rd <loopback0>:<l3vni>`, `route-target both <rt> evpn`), L3 transit SVI (`ip forward`), and anycast SVI for IRB segments — per contracts/config-artifact.md (same file as T017; depends on T017, T020)
- [X] T026 [P] [US1] Create `objects/12_overlay.yml`: seed tenant "Blue" → VRF "blue-prod" → 2 routed segments (with subnets/gateways), placement left empty (advertise-all)
- [X] T027 [P] [US1] Add `tests/unit/test_overlay.py`: `route_target` formatting and `resolve_segment_devices` advertise-all behavior (uses `src/infrahub_solution_ai_dc/overlay.py`)
- [X] T028 [US1] Validate end-to-end (quickstart §3–4): `inv load` + `inv start`, then inspect leaf/spine/super-spine `startup_configuration` artifacts and the allocated ids/RTs in the UI/GraphQL

**Checkpoint**: User Story 1 is fully functional — a routed multi-tenant overlay is generated from declared intent. **This is the MVP.**

---

## Phase 4: User Story 2 - Day-two change to an existing tenant (Priority: P2)

**Goal**: Adding/removing a segment on an existing tenant regenerates only the affected leafs' configs.

**Independent Test**: With the seed tenant in place, add a segment; confirm only the carrying leafs'
artifacts change and all other devices' artifacts are byte-identical.

- [X] T029 [US2] Exclude overlay relationships (`Device.segments`) from the Rack/Pod generator checksums in `generators/generate_rack.py` and `generators/generate_pod.py` so OverlayGenerator writes do not re-trigger the physical cascade (ADR-0004 caveat)
- [X] T030 [US2] Make `generators/generate_tenant.py` re-run idempotent for add/modify/remove: update only affected leafs' `Device.segments` and release identifiers when a segment/VRF is removed (depends on T021)
- [X] T031 [P] [US2] Add `tests/integration/test_overlay_daytwo.py`: adding a segment reconfigures only the affected leaf artifacts (scoped regeneration) — follows `tests/integration/test_infrahub.py` pattern
- [X] T032 [US2] Validate quickstart §5 (add a segment on a branch, confirm scoped artifact change)

**Checkpoint**: User Stories 1 and 2 both work; tenant changes are scoped and non-disruptive.

---

## Phase 5: User Story 3 - Control segment reach: rack placement & L2-only (Priority: P3)

**Goal**: Restrict a segment to specific racks, and support L2-only segments (no gateway).

**Independent Test**: A rack-scoped segment renders only on that rack's leaves; an L2-only segment is bridged
with no anycast SVI anywhere.

- [X] T033 [US3] Implement rack-scoped placement in `generators/generate_tenant.py` via `overlay.resolve_segment_devices` (`Segment.racks` → those racks' leafs; empty ⇒ all fabric leafs) (depends on T021)
- [X] T034 [US3] Add the L2-only branch to `transforms/templates/startup_config.j2`: render `vlan/vn-segment` + NVE `member vni <l2vni>` but skip the anycast SVI when `segment.gateway` is absent (depends on T025)
- [X] T035 [P] [US3] Extend `objects/12_overlay.yml` with a rack-scoped segment and an L2-only (no-gateway) segment example
- [X] T036 [P] [US3] Add `tests/unit/test_overlay_placement.py`: rack-scoped `resolve_segment_devices` filtering and L2-only handling
- [X] T037 [US3] Validate quickstart §6 (rack-scoped + L2-only rendering)

**Checkpoint**: All three user stories are independently functional.

---

## Phase 6: Polish & Cross-Cutting Concerns

- [X] T038 [P] Run `inv lint` (yamllint + ruff + mypy strict) and resolve findings across new/edited files
- [X] T039 [P] Run `inv test` (full unit + integration suite) and ensure green
- [X] T040 [P] Add an EVPN-overlay feature page under `docs/docs/solution-ai-dc/` (mdx) summarizing the overlay (links to CONTEXT.md/ADRs)
- [X] T041 Run the full `quickstart.md` validation end-to-end (§1–6)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: none.
- **Foundational (Phase 2)**: after Setup. **Blocks all user stories.** Internal order: schema (T003–T006) → protocols (T007) → schema-load (T008); pools/groups (T009–T011) and helpers (T012) in parallel; physical-generator edits (T013–T015) after T007/T012; baseline transform T016 → T017; menu (T018) anytime.
- **User Stories (Phase 3–5)**: all require Foundational complete.
- **Polish (Phase 6)**: after the desired stories.

### User Story Dependencies

- **US1 (P1)**: after Foundational. Self-contained MVP. (Owns the OverlayGenerator, registration, trigger, tenant config rendering, seed data.)
- **US2 (P2)**: builds on US1's OverlayGenerator/trigger; adds scoped-regeneration guarantees. Independently testable (scoped-change behavior).
- **US3 (P3)**: builds on US1's OverlayGenerator/template; adds placement filtering + L2-only. Independently testable.

### Same-file sequencing (cannot be [P])

- `transforms/startup_config.gql`: T016 (baseline) → T020 (segments).
- `transforms/templates/startup_config.j2`: T017 (baseline) → T025 (tenant) → T034 (L2-only).
- `generators/generate_tenant.py`: T021 → T030 → T033.
- `objects/12_overlay.yml`: T026 → T035.

### Parallel Opportunities

- Foundational: T003–T006 (schema files) together; then T009/T010/T011/T012/T018 together; T013/T014/T015 together (different files).
- US1: T019, T026, T027 can start in parallel; T020/T021/T024/T025 sequence per dependencies.
- Tests (T027, T031, T036) are [P] within their stories.

---

## Parallel Example: Foundational schema

```bash
# Edit the four schema files in parallel, then regenerate protocols:
Task: "Add Tenant/VRF/Segment in schemas/overlay.yml"        # T003
Task: "Edit schemas/device.yml (asn, vtep_ip, segments, roles)"  # T004
Task: "Edit schemas/logical_design.yml (overlay_asn, vtep_pool)" # T005
Task: "Edit schemas/ipam.yml (new IPPrefix roles)"           # T006
```

---

## Implementation Strategy

### MVP First (User Story 1)

1. Phase 1 Setup → 2. Phase 2 Foundational (CRITICAL — EVPN-ready fabric, no tenants) → 3. Phase 3 US1 →
4. **STOP & VALIDATE** (quickstart §3–4: routed multi-tenant overlay works) → 5. Demo.

### Incremental Delivery

- Foundational → EVPN control plane up. US1 → routed overlay (MVP). US2 → safe day-two changes. US3 →
  placement + L2-only. Each increment is independently testable and adds value without breaking the prior.

---

## Notes

- `[P]` = different files, no incomplete dependencies. Respect the same-file sequencing list above.
- Re-fetch pool-allocated values with `client.get()` (values aren't readable on the returned node).
- Verify the deployed task-worker SDK version and `from_pool`/object-load behavior early (research.md open
  items) — they affect T013 and the pool tasks.
- Commit after each task or logical group; stop at any checkpoint to validate a story independently.
