---
description: "Task list for the Server service (connect L2/L3 servers to leaves) implementation"
---

# Tasks: Connect L2/L3 Servers to Leaves via a Server Service

**Input**: Design documents from `/specs/003-server-service/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md

**Tests**: Test tasks are included because the spec's Testing Decisions and the project's `inv test` workflow
call for them (unit tests for `servers.py` helpers + fail-loud paths; an integration test for the L2/L3/
explicit journeys and idempotent re-run). They are targeted unit/integration tasks, not strict TDD-first
gates — implement alongside the code they cover.

**Organization**: Tasks are grouped by user story (US1–US3 from spec.md) for independent implementation and
testing.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: US1/US2/US3 (user-story phases only)
- All paths are repository-relative.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Confirm the working environment; no product code.

- [X] T001 Run `uv sync --all-packages` and confirm work is on branch `dga/feat-server-cilium-r9uuo`
- [X] T002 [P] Skim implementation references: `dev/adr/0002` (standalone generator), `0004` (materialized placement), `0005` (stored BGP sessions), `CONTEXT.md`, and `specs/003-server-service/` (plan/data-model/contracts/quickstart) — no file changes

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The server data model, the generalized BGP peer, IPAM/pool plumbing, shared pure helpers, and
the per-Pod server /31 pool. **All user stories depend on this.**

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

### Schema & generated types

- [X] T003 [P] Add `NetworkServerService` (`inherit_from: [GeneratorTarget]`) and `NetworkServer` (NOT `CoreArtifactTarget`; `inherit_from: [NetworkBGPPeer]`) in new `schemas/server.yml` per data-model.md
- [X] T004 [P] Edit `schemas/routing.yml`: add generic `NetworkBGPPeer` (`hostname`, `bgp_sessions` back-rel); repoint `NetworkBGPSession.device`/`peer_device` peer to `NetworkBGPPeer`; add `NetworkBGPPeer` to `NetworkDevice.inherit_from` — reconciled by removing the now-inherited `hostname`/`bgp_sessions` from `NetworkDevice`
- [X] T005 [P] Edit `schemas/device.yml`: add optional `NetworkInterface.server` owner relationship (peer `NetworkServer`, `kind: Parent`, identifier `server__interface`), make `device` optional, widen the uniqueness constraint to cover the server owner (single constraint `[device, server, name__value]`)
- [X] T006 [P] Edit `schemas/ipam.yml`: add `server_p2p` to `IpamIPPrefix.role`
- [X] T007 [P] Edit `schemas/logical_design.yml`: add `NetworkPod.server_prefix_pool` (peer `CoreIPPrefixPool`, Attribute, optional)
- [X] T008 Regenerate `src/infrahub_solution_ai_dc/protocols.py` from the schema (depends on T003–T007; do not hand-edit) — done offline: hand-added `NetworkBGPPeer`/`NetworkServer`/`NetworkServerService` + `NetworkDevice` base + `NetworkInterface.server` in the committed generator style; field lists validated against `infrahubctl protocols --schemas schemas` output. MUST be regenerated against a stack before merge (banner comment added at top of file).
- [ ] T009 Validate schema converges with `inv load-schema` (depends on T008) — DEFERRED: needs a running Infrahub stack (unavailable in this worktree). Offline proxy passed: `infrahubctl protocols --schemas schemas` loaded/parsed all schema files (exit 0) and `yaml.safe_load` succeeded for every edited schema.
- [X] T010 Regression-check the peer-generic repoint + interface change: run existing overlay unit/integration and confirm `overlay.upsert_evpn_session` and `transforms/startup_config.gql` still resolve with `NetworkBGPSession` pointing at `NetworkBGPPeer` and a nullable `NetworkInterface.device` (research.md verify items 2–3) (depends on T009) — unit suite (44 passed) + overlay import OK; `peer_device`/`device` fields intact in gql. Integration test (needs stack) deferred.

### Resource pools, IPAM & groups

- [X] T011 [P] Add a global `CoreNumberPool` "Server ASN Pool" → `NetworkServer.asn` (range 4200000000–4294967294) in `objects/07_pools.yml` per contracts/infrahub-registration.md
- [X] T012 [P] Edit `objects/04_ipam.yml`: seed a `server_p2p` supernet prefix that the PodGenerator carves per-Pod into each pod's `server_prefix_pool`
- [X] T013 [P] Add a `server_services` `CoreStandardGroup` to `objects/01_groups.yml` (do NOT add any group for `NetworkServer`)

### Shared helpers & per-Pod pool

- [X] T014 [P] Create `src/infrahub_solution_ai_dc/servers.py` with pure helpers — `select_least_utilized_rack(racks, server_counts)` (fewest servers; deterministic tie-break by rack index/name) and `select_free_server_port(interfaces)` (lowest free `role:server` interface) — plus `upsert_ebgp_session(client, logger, device, peer, local_as, remote_as)` (creates a `NetworkBGPSession` `"{a}__{b}"`, `address_family="ipv4_unicast"`, `rr_client=False`, `save(allow_upsert=True)`), modeled on `overlay.upsert_evpn_session`
- [X] T015 Extend `generators/generate_pod.py` `allocate_resource_pools()`: create + attach a per-Pod server /31 `CoreIPPrefixPool` (role `server_p2p`) on `pod.server_prefix_pool`, mirroring `prefix_pool`/`vtep_pool` (depends on T008)

### UI (optional)

- [X] T016 [P] Add a `Servers` menu group exposing `NetworkServerService`/`NetworkServer` in `menus/menu.yml`

**Checkpoint**: Schema loads; existing overlay generation is unchanged; the global Server ASN pool exists and
each pod gets a `server_prefix_pool` — no server objects yet.

---

## Phase 3: User Story 1 - L3 server (BGP-speaking / Cilium worker) (Priority: P1) 🎯 MVP

**Goal**: Declare an L3 `NetworkServerService` (VRF, no rack/ports) → the ServerGenerator materializes a
`NetworkServer` + interfaces, picks the least-utilized rack and lowest free `server` leaf port, cables the
link, allocates a /31 (both ends) and a private ASN, upserts a paired eBGP `ipv4_unicast` session on leaf and
server, and the leaf startup-config renders the interface, /31, and neighbor. Re-running changes nothing.

**Independent Test**: On a seeded fabric + VRF, create an L3 service with no rack/ports; confirm the server is
cabled to a leaf, a /31 is on both ends, an ASN is allocated, paired `ipv4_unicast` sessions exist with
correct remote-AS each side, the leaf artifact contains interface+/31+neighbor, and a re-run yields an empty
diff.

- [X] T017 [P] [US1] Create `generators/generate_server.gql` (input `$name`; service → layer/vrf(tenant/fabric)/rack/leaf_interface/segment/server shape per contracts/graphql-queries.md)
- [X] T018 [US1] Create `generators/generate_server_query.py` pydantic model mirroring the `.gql` (`_Value*` leaves, `_`-prefixed privates, `Field(alias="NetworkServerService")`) (depends on T017)
- [X] T019 [US1] Implement `ServerGenerator` (L3 path) in `generators/generate_server.py`: resolve scope via `vrf.tenant.fabric`; auto-select least-utilized rack + lowest free `role:server` leaf port (via `servers.py` + `client.filters`); create `NetworkServer` + its interface; cable server↔leaf with a `NetworkLink`; allocate `asn` (only if unset, re-fetch); allocate the /31 from the leaf pod's `server_prefix_pool` via `addressing.assign_ip_addresses_to_p2p_connections(prefix_len=31, prefix_role="server_p2p", pool=...)`; upsert paired eBGP sessions (leaf `remote_as=server.asn`, server `remote_as=fabric.overlay_asn`); set `service.server`; `update_checksum`. Ensure idempotency (deterministic server name, upsert-by-name sessions, stable /31 identifier, edge-scoped `add_relationships`, `update_group_context=False`). Fail-loud on no eligible rack/port and pool exhaustion (`vendors.py` convention) (depends on T014, T018)
- [X] T020 [US1] Exclude the server-side writes (leaf `bgp_sessions`, server-facing interface/link) from the Rack/Pod `GeneratorMixin` checksums in `generators/generate_rack.py` and `generators/generate_pod.py` so ServerGenerator writes do not re-trigger the physical cascade (ADR-0004 caveat)
- [X] T021 [US1] Register in `.infrahub.yml`: add `generate_server` query + a `generate-server` `generator_definition` (targets `server_services`, `class_name: ServerGenerator`, param `name: name__value`, `convert_query_response: false`, `execute_in_proposed_change/after_merge: false`) (depends on T017, T019)
- [X] T022 [US1] Add the ServerGenerator trigger to `triggers.yml`: `CoreGeneratorAction` `run-server-generator` + `CoreNodeTriggerRule` on `NetworkServerService` (`updated`, checksum match) (depends on T021)
- [X] T023 [US1] Extend `transforms/startup_config.gql` (per contracts/graphql-queries.md): on `bgp_sessions` add `address_family`, `local_as`, and `... on NetworkServer { interfaces … ip_address }`; ensure the `interfaces` block returns `role` + `ip_address` for `role:server` ports
- [X] T024 [US1] Extend `transforms/templates/startup_config_arista.j2`: render `role:server` port as routed (`no switchport` + /31 `ip address`) and add an `ipv4_unicast` eBGP neighbor branch — neighbor over the far-side /31, `remote-as <remote_as>`, no `update-source`, no `route-reflector-client`, activate under ipv4-unicast (per contracts/config-artifact.md) (depends on T023)
- [X] T025 [P] [US1] Mirror the same server-port + eBGP rendering into `transforms/templates/startup_config_cisco.j2` (depends on T023)
- [X] T026 [P] [US1] Mirror the same server-port + eBGP rendering into `transforms/templates/startup_config_dell.j2` (depends on T023)
- [X] T027 [P] [US1] Create `objects/13_servers.yml`: seed one L3 (Cilium worker) `NetworkServerService` in a VRF with no rack/ports — seeds `cilium-worker-1` (layer l3, VRF `["Blue", "blue-prod"]`, `member_of_groups: [server_services]`, no rack/leaf_interface/segment)
- [X] T028 [P] [US1] Create `tests/unit/test_servers.py`: `select_least_utilized_rack` (+ deterministic tie-break), `select_free_server_port`, eBGP pairing (correct `remote_as` each side), and the no-eligible-rack/port + pool-exhaustion fail-loud paths (uses `src/infrahub_solution_ai_dc/servers.py`) — 13 tests, all pass locally. Helpers are non-raising (return `None`); tests pin the `None` no-eligible-rack/no-free-port preconditions. The actual `ValueError` raising + pool-exhaustion path lives in the async `ServerGenerator` (`select_rack`/`select_leaf_port`/`allocate_server_asn`), which needs a client → covered by the integration test, not unit-testable here (noted in the file docstring)
- [X] T029 [P] [US1] Create `tests/integration/test_server_service.py`: L3 journey end-to-end (server cabled, /31 both ends, ASN, paired `ipv4_unicast` sessions) + idempotent re-run (empty diff) — follows `tests/integration/test_overlay_daytwo.py`. Written and lint/collection-clean; NOT run locally (no Dockerized Infrahub stack in this worktree). The core `test_l3_server_journey` + `test_rerun_is_empty_diff` are `@pytest.mark.skip`-marked with the same stack gate as `test_overlay_daytwo.test_scoped_regeneration` (objects/ not registered in `.infrahub.yml`, triggers parked in `objects/20_triggers.yml.save`). CI/stack command: `uv run pytest tests/integration/test_server_service.py`
- [ ] T030 [US1] Validate end-to-end (quickstart §4–6): `inv load` + `inv start`, inspect the `NetworkServer`, the leaf `Startup configuration` artifact (interface + /31 + eBGP neighbor), confirm no server artifact exists, and confirm a re-run is a no-op — DEFERRED: requires a running Infrahub stack (unavailable in this worktree; must NOT compete with the unrelated Docker stack up). Offline substitutes done: `objects/13_servers.yml` parses via `yaml.safe_load_all` and references the real seeded VRF `["Blue", "blue-prod"]`; rendered-config contract re-read (`contracts/config-artifact.md`, quickstart §5). Stack runbook to complete: `inv load` → `inv start`, then verify per quickstart §4–6 (NetworkServer cabled + /31 both ends + ASN + paired `ipv4_unicast` sessions; leaf `Startup configuration` renders interface/​/31/​eBGP neighbor; no server artifact; re-run = empty diff)

**Checkpoint**: User Story 1 is fully functional — an L3 server is connected from a single design object.
**This is the MVP.**

---

## Phase 4: User Story 2 - L2 server (bridged into a Segment) (Priority: P2)

**Goal**: Declare an L2 `NetworkServerService` (VRF + Segment, no rack/ports) → the generator materializes the
server, cables it to a leaf, and adds that leaf's Rack to the Segment's `racks` placement. No fabric-side BGP
or IP.

**Independent Test**: On a VRF with a Segment, create an L2 service naming it; confirm the server is cabled to
a leaf whose Segment placement now includes that Rack, and that no BGP session or /31 was created.

- [X] T031 [US2] Extend `generators/generate_server.py` with the L2 branch: reuse placement/cabling from US1; idempotently add the chosen leaf's Rack to `NetworkSegment.racks` via `add_relationships("racks", …)`; create **no** BGP session and **no** /31/ASN (depends on T019) — L2 `else` branch calls new `attach_segment_rack()` (edge-scoped `add_relationships`, no-op if the rack edge already exists); no `configure_l3` call so no ASN/​/31/session on L2
- [X] T032 [US2] Add fail-loud validation to `generators/generate_server.py` / `servers.py`: L2 without `segment` or with `segment.vrf != service.vrf` → error; L3 that also names a `segment` (contradictory) → error — no partial objects (`vendors.py` convention) (depends on T019, T031) — implemented as PURE synchronous `servers.validate_service(layer, service_name, service_vrf_id, segment_id, segment_vrf_id)` raising `ValueError`; the generator calls it BEFORE any write (no partial objects). All three fail-loud paths are decidable from the query response (segment + its `vrf.id` are already selected), so no async graph read needed — directly unit-testable
- [X] T033 [P] [US2] Extend `objects/13_servers.yml` with an L2 `NetworkServerService` example naming an existing Segment under the same VRF — seeded `web-host-1` (layer l2, VRF `["Blue", "blue-prod"]`, `segment: "blue-l2"` — the L2-only segment under the same VRF, seeded in `objects/12_overlay.yml`)
- [X] T034 [P] [US2] Extend `tests/unit/test_servers.py` and `tests/integration/test_server_service.py`: L2 journey (Segment `racks` grows, no session/IP) and the segment-not-in-VRF + contradictory-L3+Segment fail-loud paths (depends on T028, T029) — added `TestValidateService` (5 unit tests: L3-no-segment valid, L2-in-VRF valid, L2-missing-segment, L2-segment-other-VRF, L3+segment contradictory) — all pass locally; added stack-gated `test_l2_server_journey` (racks grows, no ASN/​/31/session) `@pytest.mark.skip`-marked like the existing L3 journey
- [ ] T035 [US2] Validate quickstart §7 (L2 attachment: placement grows, no BGP/IP) — DEFERRED: needs a running Infrahub stack (unavailable in this worktree). Offline substitutes done: `objects/13_servers.yml` parses via `yaml.safe_load_all` and the L2 service references the real seeded VRF `["Blue", "blue-prod"]` + existing segment `blue-l2`; unit-level fail-loud + L2 intent validation green. Stack runbook to complete: `inv load` → `inv start`, then per quickstart §7 create/confirm the L2 service → assert a `NetworkServer` cabled to a leaf, that leaf's Rack now in the segment's `racks`, and NO `NetworkBGPSession`/​/31 (run `uv run pytest tests/integration/test_server_service.py::TestServerServiceL3::test_l2_server_journey` with the skip lifted)

**Checkpoint**: User Stories 1 and 2 both work independently.

---

## Phase 5: User Story 3 - Explicit placement (honor-or-fail) (Priority: P3)

**Goal**: A service naming a specific Rack and/or leaf port uses exactly those when valid; an invalid choice
fails loudly and produces nothing.

**Independent Test**: Create a service naming an occupied leaf port → the generator errors clearly and creates
no partial objects; a service naming a valid free Rack+port uses exactly that Rack+port.

- [X] T036 [US3] Extend `generators/generate_server.py`: when `rack`/`leaf_interface` are provided, honor them exactly (validate rack ∈ VRF's Fabric, port free + `role:server`); fail loud on any invalid explicit placement (occupied/wrong-role port, rack with no free port, port not on a leaf of the rack) producing no partial objects; keep last-free-port contention deterministic (at most one wins) (depends on T019) — `resolve_placement` now branches: no `rack`/`leaf_interface` ⇒ existing auto path; either present ⇒ new `resolve_explicit_placement()`. Validation (all reads, before any write ⇒ no partial objects): rack∈fabric (`_fabric_rack_ids`), rack-without-port falls back to `select_leaf_port`, named port re-fetched with `include=["ip_address","link","device"]` (the `.gql` omits ip/link), leaf resolved + rack derived-or-checked, port-on-a-leaf-of-the-rack check, then pure `servers.validate_explicit_port(port, rack_name)` (role:server + free). Last-free-port contention is NOT locked in-generator: both racers pass the read-time check, but Infrahub's interface/link uniqueness + upsert-by-name on `save` means at most one link materializes and the loser's `save` fails loud (documented in the method docstring)
- [X] T037 [P] [US3] Extend `tests/unit/test_servers.py` / integration: honor a valid explicit Rack+port; fail-loud on an occupied port and on a rack with no free port; assert nothing is created on failure (depends on T028, T029) — added pure `TestValidateExplicitPort` (5 unit tests: free-port honored, occupied-cabled fails, ip-address fails, wrong-role fails, explicit-rack-no-free-port ⇒ `select_free_server_port` None) — all pass locally (23 in file / 67 full unit suite). Added stack-gated `test_explicit_placement_honored` + `test_explicit_occupied_port_fails_loud` (assert no `NetworkServer` on failure) to the integration file, `@pytest.mark.skip`-marked like the L3 journey. CI/stack: `uv run pytest tests/integration/test_server_service.py`
- [ ] T038 [US3] Validate quickstart §8 (explicit placement honored; every invalid path fails loud with no partial objects) — DEFERRED: needs a running Infrahub stack (unavailable in this worktree). Offline substitutes done: pure explicit-placement validators unit-green; async fail-loud paths coverage written skip-gated; `inv lint` clean. Stack runbook to complete: `inv load` → `inv start`, then per quickstart §8 — (a) create a service naming a valid free Rack + `role:server` leaf port ⇒ assert exactly that rack/port is used; (b) create services naming an occupied port, a wrong-role port, a rack with no free port, a port not on a leaf of the named rack, and a rack outside the VRF's fabric ⇒ each errors clearly and creates no `NetworkServer` (no partial objects). Lift the skips on `test_explicit_placement_honored` / `test_explicit_occupied_port_fails_loud`

**Checkpoint**: All three user stories are independently functional.

---

## Phase 6: Polish & Cross-Cutting Concerns

- [ ] T039 [P] Run `inv lint` (yamllint + ruff ALL + mypy strict) and resolve findings across new/edited files
- [ ] T040 [P] Run `inv test` (full unit + integration suite) and ensure green
- [ ] T041 [P] Add a "Connect servers" feature note under `dev/` (or `docs/`) summarizing the Server service (links to ADR-0002/0004/0005 and CONTEXT.md)
- [ ] T042 Run the full `quickstart.md` validation end-to-end (§1–8)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: none.
- **Foundational (Phase 2)**: after Setup. **Blocks all user stories.** Internal order: schema (T003–T007) → protocols (T008) → schema-load (T009) → regression check (T010); pools/groups (T011–T013), helpers (T014) and menu (T016) in parallel; pod-pool edit (T015) after T008.
- **User Stories (Phase 3–5)**: all require Foundational complete.
- **Polish (Phase 6)**: after the desired stories.

### User Story Dependencies

- **US1 (P1)**: after Foundational. Self-contained MVP. Owns the ServerGenerator (L3 path), registration, trigger, template rendering, seed, and the loop-prevention checksum exclusion.
- **US2 (P2)**: builds on US1's ServerGenerator (adds the L2 branch + L2/contradiction fail-loud). Independently testable (Segment placement, no BGP/IP).
- **US3 (P3)**: builds on US1's ServerGenerator (adds explicit-placement honor-or-fail). Independently testable (honor + fail-loud).

### Same-file sequencing (cannot be [P])

- `generators/generate_server.py`: T019 (L3) → T031 (L2) → T032 (L2 validation) → T036 (explicit).
- `transforms/startup_config.gql`: T023 only.
- `transforms/templates/startup_config_arista.j2`: T024 (cisco/dell mirrors T025/T026 are separate files → [P]).
- `objects/13_servers.yml`: T027 → T033.
- `tests/unit/test_servers.py`: T028 → T034 → T037. `tests/integration/test_server_service.py`: T029 → T034 → T037.
- `generators/generate_pod.py`: T015 (pool) then T020 (checksum exclusion). `generators/generate_rack.py`: T020.

### Parallel Opportunities

- Foundational: T003–T007 (schema files) together; then T011/T012/T013/T014/T016 together; T015 after T008.
- US1: T017, T027, T028, T029 can start in parallel; T025/T026 (cisco/dell templates) in parallel after T023; the T018→T019→T021→T022 and T023→T024 chains are sequential.
- Different user stories can proceed in parallel once Foundational is done (they share `generate_server.py`, so coordinate that file per the sequencing list).

---

## Parallel Example: Foundational schema

```bash
# Edit the schema files in parallel, then regenerate protocols:
Task: "Add NetworkServerService + NetworkServer in schemas/server.yml"          # T003
Task: "Add NetworkBGPPeer generic + repoint NetworkBGPSession in schemas/routing.yml"  # T004
Task: "Add optional server owner on NetworkInterface in schemas/device.yml"     # T005
Task: "Add server_p2p role in schemas/ipam.yml"                                 # T006
Task: "Add NetworkPod.server_prefix_pool in schemas/logical_design.yml"         # T007
```

---

## Implementation Strategy

### MVP First (User Story 1)

1. Phase 1 Setup → 2. Phase 2 Foundational (CRITICAL — schema + pools + helpers, existing overlay unaffected)
→ 3. Phase 3 US1 → 4. **STOP & VALIDATE** (quickstart §4–6: L3 server connected, config rendered, idempotent)
→ 5. Demo.

### Incremental Delivery

- Foundational → server data model + pools ready. US1 → L3 Cilium worker connected (MVP). US2 → L2 host into a
  Segment. US3 → explicit placement honor-or-fail. Each increment is independently testable and adds value
  without breaking the prior.

### Parallel Team Strategy

After Foundational: one developer drives US1 (owns `generate_server.py`), then US2 and US3 layer on the same
generator — coordinate that single file via the same-file sequencing list; tests and seed data are [P].

---

## Notes

- `[P]` = different files, no incomplete dependencies. Respect the same-file sequencing list above.
- Re-fetch pool-allocated values with `client.get()` (values aren't readable on the returned node); allocate
  `NetworkServer.asn` only if unset (research.md verify item 1).
- `NetworkServer` must never join `devices`/`{vendor}_devices` or gain a startup-config artifact.
- Server↔leaf is **eBGP** (`ipv4_unicast`, `rr_client: false`), server ASN from the 32-bit private pool,
  distinct from the 16-bit overlay ASN range.
- For the L2 path, whether adding a Rack to `Segment.racks` should auto-re-trigger the OverlayGenerator is a
  research.md open item (SD8) — v1 default keeps overlay materialization a separate step.
- Commit after each task or logical group; stop at any checkpoint to validate a story independently.
