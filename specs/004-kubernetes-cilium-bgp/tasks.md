---

description: "Task list for feature implementation"
---

# Tasks: Model Kubernetes Clusters Spanning Multiple Servers and Render Cilium BGP CRDs

**Input**: Design documents from `specs/004-kubernetes-cilium-bgp/`

**Prerequisites**: `plan.md`, `spec.md`, `research.md`, `data-model.md`, `contracts/`, `quickstart.md`, `critiques/critique-20260729-195324.md`

**Tests**: Unit tests only, per the source PRD's agreed Testing Decisions. **No integration or contract test tasks are generated** — the Server service's own integration suite is entirely `@pytest.mark.skip`-marked (verified, `research.md` R6b), so adding cluster integration tests would add skipped tests rather than coverage. Acceptance is manual via `quickstart.md`.

**Organization**: Tasks are grouped by user story. Note the honest caveat below on independence.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: Which user story this task belongs to (US1, US2, US3, US4)
- Exact file paths are given in every task

## Path Conventions

Existing Infrahub solution repository layout (per `plan.md` Structure Decision): shared library in `src/infrahub_solution_ai_dc/`, transforms in `transforms/`, schema YAML in `schemas/`, seed data in `objects/`, unit tests in `tests/unit/`, plus a new top-level `queries/` directory.

## ⚠️ Read before starting: two things constrain the ordering

**1. Story independence is limited here, and pretending otherwise would mislead.** The template's model assumes stories are independently implementable. In this feature:

- **US1 (P1) requires essentially the whole production surface.** There is no smaller slice that renders a correct manifest.
- **US2 (P2) adds no production code at all.** Add / remove / move already work if US1's peering module is a pure function of its members. US2's phase is therefore tests plus manual verification, and that is the honest content — not a gap.
- **US3 (P3) adds no new module.** Its eligibility logic lands inside US1's `clusters.py` (it is one of the module's stated responsibilities). US3's phase is the L2 seed plus the exclusion tests.
- **US4 (P3) is genuinely independent** and may be done at any point after Phase 2.

**2. `mypy .` is a hard gate, not a preference.** `src/infrahub_solution_ai_dc/protocols.py` is generated from the live schema. Until T009 regenerates it, it contains no `NetworkKubernetesCluster` and no `NetworkServer.node_selector`, and CI's `mypy .` fails on any code referencing them. No amount of test-writing works around this. Phase 2 must complete before any typed work begins.

---

## Phase 1: Setup

**Purpose**: Establish a known-good baseline and the one new directory.

- [X] T001 Confirm a clean baseline by running `inv lint` and `inv test` and recording that both pass before any change — every later "existing suite still passes" check (FR-009) is meaningless without this reference point — **baseline recorded 2026-07-29, clean**: `uv run pytest tests/unit -q` → `107 passed in 0.14s`; `uv run inv lint` → rumdl "No issues found in 75 files", yamllint clean, ruff "All checks passed!", mypy "no issues found in 42 source files". `tests/integration` collects 15 tests, **all `@pytest.mark.skip`-marked**, and spins its own `infrahub_testcontainers` stack — which is why plain `inv test` runs for many minutes. Prefer `pytest tests/unit` for the fast inner loop
- [X] T002 [P] Create the `queries/` directory at the repository root with a `.gitkeep`, per `plan.md` Structure Decision (it holds the standalone `ArtifactIDs` read surface, which backs neither a generator nor a transform) — **already satisfied**: `queries/.gitkeep` is present and tracked (committed in `946dbfb`), so `plan.md`'s "the one genuinely new location is `queries/`" is stale. Nothing to create; the location is confirmed available for T0xx's `artifact_ids.gql`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Schema, seed data, and the generated-definitions regeneration that unblocks all typed work.

**⚠️ CRITICAL**: No user story work can begin until T009 completes.

### Schema

- [X] T003 Create `schemas/kubernetes.yml` defining node `KubernetesCluster` in namespace `Network` per `data-model.md` §1 — attributes `name` (Text, required, `unique: true`) and `description` (Text, optional); relationship `members` → `NetworkServerService` (kind `Generic`, cardinality `many`, optional, identifier `kubernetes_cluster__members`); `inherit_from: [CoreArtifactTarget]`; `human_friendly_id: [name__value]`; `display_label: name__value`; `order_by: ["name__value"]`. Do **not** inherit `GeneratorTarget` — there is no new generator (ADR-0002) — **done**; one deviation from `data-model.md` §1: Infrahub caps a description at **128 characters**, so the `members` description is the short form ("Server services forming this cluster. L3 members become BGP peers in the rendered manifest; L2 members are skipped."). The schema load rejected the longer wording outright with `string_too_long`
- [X] T004 Extend `schemas/server.yml` on `NetworkServerService` with relationship `kubernetes_cluster` → `NetworkKubernetesCluster` (kind `Attribute`, **cardinality `one`**, `optional: true`, identifier `kubernetes_cluster__members`, `order_weight: 8000`) per `data-model.md` §2 — cardinality `one` is what makes FR-001's "a second cluster is rejected" true by construction rather than by generator code — **done**; confirmed typed as `kubernetes_cluster: RelationshipAttribute[NetworkKubernetesCluster]` after T009
- [X] T005 Extend `schemas/server.yml` on `NetworkServer` with the `node_selector` computed attribute per `data-model.md` §3 — `kind: Text`, `read_only: true`, `optional: true`, `computed_attribute.kind: Jinja2`, template `{{ hostname__value | replace("server-", "", 1) }}`, `order_weight: 3500`, and a description telling the operator to apply it as `infrahub.io/server=<value>`. The count-limited `replace(..., 1)` is deliberate: an unanchored replace would mangle a service legitimately named e.g. `server-side-cache` — **done**; same 128-character description cap applied as T003, so the wording is shortened to "Server hostname minus the `server-` prefix. Label the node `infrahub.io/server=<value>` to match the rendered Cilium manifest." (126 chars), which keeps the operator instruction intact. Typed as `node_selector: StringOptional` after T009

### Seed data

- [X] T006 [P] Add the `kubernetes_clusters` standard group to `objects/01_groups.yml` per `contracts/infrahub-registration.md`, with a comment recording that it is deliberately **not** parented under `devices` so the per-vendor startup-config artifacts never sweep a cluster up — **done**; verified by loading the file against the stack (`Created node: kubernetes_clusters`)
- [X] T007 [P] Create `objects/09_kubernetes.yml` declaring the `cilium-demo` `NetworkKubernetesCluster` with `member_of_groups: ["kubernetes_clusters"]` per `contracts/infrahub-registration.md`. Numbered `09` so the cluster exists before the services in `13_servers.yml` reference it — **done**; loaded successfully and `infrahubctl object get NetworkKubernetesCluster` returns `cilium-demo` with `members: ""`, which is live confirmation that FR-005's zero-member cluster is valid
- [X] T008 Extend `objects/13_servers.yml` per the membership table in `contracts/infrahub-registration.md` — add `kubernetes_cluster: "cilium-demo"` to the existing `cilium-worker-1` (l3) and `web-host-1` (l2) services, and add two new l3 services `cilium-worker-2` and `cilium-worker-3` matching the existing seeds' shape (`layer: l3`, `vrf: ["Blue", "blue-prod"]`, no rack / leaf_interface / segment, `member_of_groups: ["server_services"]`). Leave `green-cilium-worker-1` and `green-web-host-1` **unclustered** — they are the evidence for FR-001's "valid with none". Automatic placement is what spreads the three L3 members across racks and so gives the manifest distinct `peerAddress` values — **done**; six services now seeded, four clustered (`cilium-worker-1/-2/-3` l3 + `web-host-1` l2) and the two `green-*` left unclustered. Not load-verified: `13_servers.yml` needs the full fabric/rack/overlay chain, which is out of this chunk's scope

### The gate

- [X] T009 Run `inv load-schema` against a running stack, then regenerate `src/infrahub_solution_ai_dc/protocols.py` so `NetworkKubernetesCluster` and `NetworkServer.node_selector` become typed. Verify with `inv lint` that `mypy` sees the new kind. **This blocks every subsequent phase** — see `data-model.md` §Migration and `research.md` R6a — **done**, and it discharged the feature-003 hand-editing debt: the old header note is gone and the file is now genuinely generated (744 → 786 lines). Three consequences worth knowing before the next phase:
  1. **All 23 names the repo imports from `protocols.py` survived** (verified by AST-walking every `from ...protocols import` site); `NetworkKubernetesCluster`, `NetworkServerService.kubernetes_cluster` and `NetworkServer.node_selector` are all present. Async flavour retained (`RelationshipManager`, not `...Sync`)
  2. SDK 1.22's generator emits **parameterised** relationship generics (`RelationshipManager[CoreArtifact]`) where the previous file had bare `RelationshipManager`/`RelatedNode`. That narrowing of an invariant generic on override produces 42 mypy `[assignment]` errors *inside the generated file*. Resolved with a per-module `disable_error_code = ["assignment"]` override in `pyproject.toml` scoped to `infrahub_solution_ai_dc.protocols` only — every other code still applies there, and use sites elsewhere are checked normally
  3. The same parameterisation surfaced 8 **real** type errors in `transforms/cabling_plan.py`: its `# type: ignore[union-attr]` comments no longer matched, because `link.endpoints.peers[*].peer` is now typed to the `NetworkEndpoint` generic, which declares neither `device` nor `name`. Fixed properly rather than by re-coding the ignores — two `cast("NetworkInterface", ...)` binds at the existing `get_kind()` guard, which removed all eight ignores. Also note the generator emits duplicate `parent`/`children` fields for hierarchical generics (`NetworkBuildingBlock`, `LocationPhysical`) that `ruff` rejects; the identical trailing pair is stripped after each regeneration, and the file header now records that step

**Checkpoint**: Schema converged, seed data in place, typed definitions regenerated. Typed work can now begin.

---

## Phase 3: User Story 1 — Declare a Cilium cluster and get both sides configured (Priority: P1) 🎯 MVP

**Goal**: An operator declares a cluster plus N L3 members; the fabric provisions each member unchanged, and the cluster carries a ready-to-deploy Cilium manifest mirroring every stored session.

**Independent Test**: On a seeded fabric, the `cilium-demo` cluster's `Cilium BGP Manifest` artifact contains one `CiliumBGPClusterConfig` per L3 member whose `localASN`, `peerASN` and `peerAddress` match that member's stored session and leaf address, plus one peer config and one advertisement.

### Unit tests for User Story 1

> Write these first and confirm they fail before implementing T013–T017.

- [ ] T010 [P] [US1] Extend `tests/unit/test_computed_attribute.py` with a parametrized test for the `node_selector` template, rendering it via `infrahub_sdk.template.Jinja2Template` as the existing `test_intf_index` does — assert `server-cilium-worker-1` → `cilium-worker-1` (FR-002), and add a case proving the count-limited replace leaves an inner occurrence intact (`server-server-side-cache` → `server-side-cache`)
- [ ] T011 [P] [US1] Create `tests/unit/test_clusters.py` covering the peering module's happy path with plain stub objects (no client, mirroring `tests/unit/test_servers.py`) — two eligible L3 members produce two `CiliumPeering` records with `local_asn` from the server-side session's `local_as`, `peer_asn` from its `remote_as`, `peer_address` from the cabled leaf port's IP **with the `/31` stripped**, and `node_selector` from the server
- [ ] T012 [P] [US1] Create `tests/unit/test_cilium_manifest.py` asserting the rendered manifest for a two-eligible-L3-member fixture, parsed with `yaml.safe_load_all` — document count is N + 2, kinds and order are N × `CiliumBGPClusterConfig` then `CiliumBGPPeerConfig` then `CiliumBGPAdvertisement`, every field matches `contracts/cilium-manifest-artifact.md`, `peerConfigRef.name` equals the peer config's `metadata.name`, and the advertisement's labels satisfy the peer config's `families[].advertisements.matchLabels` selector. Assert on parsed structure only — never on rendered whitespace, key order, or template internals

### Implementation for User Story 1

- [ ] T013 [US1] Create `src/infrahub_solution_ai_dc/clusters.py` with the `CiliumPeering` `NamedTuple` (`node_selector`, `local_asn`, `peer_asn`, `peer_address`, `instance_name`) per `data-model.md` §5, following the `ProcessedInputData` convention in `transforms/cabling_plan.py`. Pure module — no `client`, no I/O — so it is unit-testable with plain stubs like `servers.py` and `overlay.py`
- [ ] T014 [US1] Implement the field mapping in `src/infrahub_solution_ai_dc/clusters.py` — read `local_asn`/`peer_asn` from the **server-side** session (where the generator writes `local_as=server_asn, remote_as=overlay_asn`, `generators/generate_server.py:693-695`), and `peer_address` by walking server → interfaces → link → endpoints → the `NetworkInterface` end → `ip_address`, stripping the prefix length. Selecting the wrong end of the link yields the *server's* address — a plausible-looking but wrong `peerAddress`
- [ ] T015 [US1] Implement **deterministic** interface selection in `src/infrahub_solution_ai_dc/clusters.py` — iterate the server's interfaces sorted by interface name and take the first eligible one, not "the first found" (which is query order). Per critique finding E1: a second cabled interface would otherwise let `peer_address` flip between renders, churning the checksum and making Vidra re-sync forever
- [ ] T016 [US1] Implement deterministic across-member ordering in `src/infrahub_solution_ai_dc/clusters.py` — sort the returned records by `node_selector`. This is what makes the artifact checksum stable, which is what makes Vidra's checksum comparison meaningful (FR-008); without it an unchanged fabric re-renders differently every time
- [ ] T017 [US1] Create `transforms/cilium_manifest.gql` per `contracts/graphql-queries.md` §1 — input `$name: String!`, returning cluster → members → `layer`, and per member the server's `hostname`, `node_selector`, `asn`, `bgp_sessions` (`address_family`, `local_as`, `remote_as`) and `interfaces` → `link` → `endpoints` with `__typename` plus an inline `... on NetworkInterface { ip_address { node { address { value } } } }` fragment. The `__typename` discrimination is required to pick the leaf end
- [ ] T018 [US1] Create `transforms/cilium_manifest_query.py` — the Pydantic response model for T017's query, following the repo convention shown in `transforms/fabric_cabling_plan_query.py` (`_Value*` leaf models, `_`-prefixed privates, `Field(alias=...)`), used with `convert_query_response: false`
- [ ] T019 [US1] Create `transforms/cilium_manifest.py` — an `InfrahubTransform` subclass `CiliumManifest` with `query = "cilium_manifest"` and `async def transform(self, data)`, modelled on `transforms/cabling_plan.py`. Build plain dicts and serialise with `yaml.safe_dump_all`; hold **no** selection or eligibility logic (that is T013–T016's job). Python serialisation rather than Jinja2 is deliberate — it makes the empty case (FR-005) valid by construction, per `research.md` R5
- [ ] T020 [US1] Register the manifest artifact in `.infrahub.yml` per `contracts/infrahub-registration.md` — query `cilium_manifest`; `python_transforms` entry (`class_name: CiliumManifest`) **with the `watch: files: [src/infrahub_solution_ai_dc/]` entry**, which is required not optional because the transform imports the peering module from outside the `./transforms` closure Infrahub detects; and the `artifact_definitions` entry with `artifact_name: "Cilium BGP Manifest"`, `content_type: "application/yaml"`, `targets: "kubernetes_clusters"`, `parameters: {name: "name__value"}`. **`artifact_name` is a published contract with Vidra** — renaming it breaks deployed clusters silently. Add **no** `generator_definitions` entry
- [ ] T021 [US1] Run `inv lint` and `inv test`, and confirm the existing Server service unit suites (`tests/unit/test_server_generator.py`, `tests/unit/test_servers.py`) pass with **zero edits** — that is FR-009's real check. If either needed changing, clustering has leaked into member provisioning and T013–T020 must be revised

**Checkpoint**: US1 fully functional. Manifest renders for the demo cluster with matching ASNs and addresses on both sides (SC-002, SC-004).

---

## Phase 4: User Story 2 — Add or remove a member on a live cluster (Priority: P2)

**Goal**: Growing, shrinking or re-placing a cluster re-renders only that cluster's manifest, changing nothing else.

**Independent Test**: Render an N-member and an N+1-member fixture and confirm the document count differs by exactly one with the shared documents unchanged; render a member on a different leaf and confirm `peerAddress` follows.

**Note**: This story adds **no production code**. Add / remove / move already work because T013–T016 make the manifest a pure function of its members, and artifacts re-render on their query's data dependency with no trigger rule needed (`research.md` R7). The tasks below are the verification that this holds.

### Unit tests for User Story 2

- [ ] T022 [P] [US2] Add to `tests/unit/test_cilium_manifest.py` a fixture-differencing test for member count — render N-member and N+1-member fixtures, assert the `CiliumBGPClusterConfig` count differs by exactly one, and assert the `CiliumBGPPeerConfig` and `CiliumBGPAdvertisement` documents are byte-identical between the two renders (FR-006, US2 scenarios 1–2)
- [ ] T023 [P] [US2] Add to `tests/unit/test_cilium_manifest.py` a move test — render a fixture whose member is cabled to a different leaf with a different /31 and assert `peerAddress` follows the new leaf while every other field is unchanged (FR-006, US2 scenario 3)
- [ ] T024 [P] [US2] Add to `tests/unit/test_clusters.py` an ordering-stability test — build the same members in shuffled input order and assert the returned records are identical, proving checksum stability does not depend on fetch order

### Verification for User Story 2

- [ ] T025 [US2] Record in `tasks.md` progress notes (or the PR description) that FR-006's **trigger half** — that Infrahub actually re-renders on add / remove / move — is verified only manually via `quickstart.md` step 6, not by T022–T024, which verify only that the manifest is a function of its members. Per critique finding P4, this split must be stated so the unit tests are not mistaken for full FR-006 coverage

**Checkpoint**: US1 and US2 both verified.

---

## Phase 5: User Story 3 — Mixed L2/L3 cluster (Priority: P3)

**Goal**: L2 members belong to a cluster without appearing in the manifest; an all-L2 or empty cluster renders an empty manifest rather than failing.

**Independent Test**: Render a cluster with two L3 and one L2 member and confirm exactly two cluster-config documents with the L2 member appearing nowhere; render an all-L2 cluster and confirm zero documents and no raise.

**Note**: The eligibility logic lives in `clusters.py` as one of the module's stated responsibilities, so T027 extends the US1 module rather than adding a new one. The L2 seed data already landed in T008.

### Unit tests for User Story 3

- [ ] T026 [P] [US3] Add to `tests/unit/test_clusters.py` eligibility tests for every exclusion in `data-model.md` §5 — an L2 member, an L3 member with no resolved server, an L3 member with no `ipv4_unicast` server-side session, an L3 member with a null `local_as` or `remote_as`, and an L3 member whose cabling resolves to no leaf-port IP. Each must be omitted, and **none** may raise (FR-004, FR-005)
- [ ] T027 [P] [US3] Add to `tests/unit/test_cilium_manifest.py` the mixed-cluster and empty-cluster render tests — a 2 × L3 + 1 × L2 fixture yields exactly two cluster-config documents with the L2 member's `node_selector` appearing **nowhere** in the rendered body (US3 scenario 1); an all-L2 fixture and a zero-member fixture each yield zero documents and raise nothing, and specifically do **not** emit the two shared documents on their own (FR-005, US3 scenario 2, per `contracts/cilium-manifest-artifact.md`); a fixture with one complete and one incomplete L3 member yields only the complete one (US3 scenario 3)

### Implementation for User Story 3

- [ ] T028 [US3] Implement the eligibility filter in `src/infrahub_solution_ai_dc/clusters.py` applying all five checks from `data-model.md` §5, omitting rather than raising — the one place this feature deliberately does not fail loud, so that one mid-provisioning member never withholds valid config from the rest
- [ ] T029 [US3] Add omission logging to `src/infrahub_solution_ai_dc/clusters.py` — log each omitted member with the specific eligibility check it failed. Per critique finding E2: the spec concedes a permanently broken member is otherwise "detectable only as member count not matching document count", i.e. only by a human counting. This changes no rendered output and does not weaken the omit-don't-raise decision; it makes it diagnosable

**Checkpoint**: All rendering behaviour verified, including the exclusion and empty cases.

---

## Phase 6: User Story 4 — Poll the artifact for change from outside (Priority: P3)

**Goal**: Vidra can cheaply detect whether the fabric changed before re-syncing.

**Independent Test**: Run the `ArtifactIDs` query against a stack with a rendered cluster artifact and confirm it returns the artifact's id, storage id and checksum; run it twice on an unchanged fabric and confirm the checksum is identical.

**Note**: Genuinely independent of US1–US3 — may be done at any point after Phase 2.

- [ ] T030 [P] [US4] Create `queries/artifact_ids.gql` containing the `ArtifactIDs` query **copied verbatim** from `contracts/graphql-queries.md` §2. Every part of its shape is fixed by Vidra: query name `ArtifactIDs` (Vidra's `defaultQueryName`), variable `$artifactname` typed **`[String]`** (a list) matched with **`name__values`** (plural), and fields `id`, `storage_id { id }`, `checksum { value }`, `name { value }`. Getting the variable type or plurality wrong returns an empty result rather than an error. **Do not "fix" `storage_id { id }` to `{ value }`** — it looks wrong but is verified correct against both Infrahub introspection and Vidra's Go unmarshalling; see the do-not-change note in the contract
- [ ] T031 [US4] Register the query in `.infrahub.yml` as `name: ArtifactIDs` → `file_path: "./queries/artifact_ids.gql"`, keeping the exact casing — the registered name forms the `/api/query/{name}` path Vidra calls, and Vidra's default is that literal string

**Checkpoint**: All four user stories complete.

---

## Phase 7: Polish & Cross-Cutting Concerns

- [ ] T032 [P] Update `AGENTS.md` — add `clusters.py` to the Core Library list ("Cluster peering: turns a cluster's members into ordered Cilium peering records; eligibility and deterministic ordering; pure, no client"), add `cilium_manifest.py` to the Transforms section, and note the new `queries/` directory and the `application/yaml` artifact. `AGENTS.md` is the single source of truth for repository structure and is currently silent on all of it
- [ ] T033 [P] Add glossary entries to `CONTEXT.md` for **Kubernetes cluster**, **cluster member**, **node selector**, **Server service** and **Server**. Verified: `CONTEXT.md` currently has no entry for any of these terms — the source PRD flagged this as pending documentation with a draft written alongside it and never applied. Since `CONTEXT.md` is the project's domain-language source of truth, leaving five new domain terms out of it is a real gap
- [ ] T034 [P] Record the multi-cluster bound where an implementer will actually hit it — a comment in `.infrahub.yml` beside the `cilium_bgp_manifest` artifact definition noting that all artifacts of one definition share one name, that Vidra selects by name only and syncs every match, and that v1 therefore supports one Cilium-consuming cluster per Infrahub branch (critique finding P1; full reasoning in `spec.md` Assumptions and `contracts/cilium-manifest-artifact.md`)
- [ ] T035 Consider whether an ADR is warranted for the one-cluster-config-per-member decision and record it in `dev/adr/` if so — the decision rests on a verified external constraint (`peerAddress` is not expressible in `CiliumBGPNodeConfigOverride`, `research.md` R1) that a future reader would otherwise have to re-derive, which is exactly the ADR criterion the existing `dev/adr/0001`–`0006` follow. If judged not warranted, note why and move on rather than writing a thin record
- [ ] T036 Run `inv lint` and `inv format` and confirm clean — `ruff` with `select = ["ALL"]`, `mypy` strict, `yamllint` at 140 chars, and `rumdl` over the new markdown
- [ ] T037 Walk `quickstart.md` end to end against a running stack and tick its Success checklist — this is the **acceptance verification** for this feature, since there are no integration tests. Steps 5–7 cover FR-003, FR-008, SC-002 and SC-004; step 6 is the only verification of FR-006's trigger half and of the empty-manifest withdrawal question (critique finding P3)

---

## Dependencies & Execution Order

### Phase dependencies

- **Phase 1 (Setup)**: no dependencies
- **Phase 2 (Foundational)**: depends on Phase 1. **T009 blocks every later phase** — the `mypy` gate
- **Phase 3 (US1, P1)**: depends on T009
- **Phase 4 (US2, P2)**: depends on Phase 3 (its tests extend US1's test files and exercise US1's module)
- **Phase 5 (US3, P3)**: depends on Phase 3 for the same reason; T028–T029 extend `clusters.py`
- **Phase 6 (US4, P3)**: depends only on T009 — fully parallel with Phases 3–5
- **Phase 7 (Polish)**: T032–T035 depend only on the relevant code existing; T036–T037 depend on everything

### Within Phase 2

- T003 → T004, T005 (the new kind must exist before the relationship pointing at it)
- T006, T007 are parallel with each other and with T003–T005
- T008 depends on T004 (the `kubernetes_cluster` field must exist) and T007 (the cluster must exist)
- T009 depends on all of T003–T008

### Within Phase 3

- T010, T011, T012 are parallel (three different test files/areas) and precede their implementations
- T013 → T014 → T015, T016 (same file, sequential)
- T017 → T018 (the model mirrors the query)
- T019 depends on T013–T016 and T018
- T020 depends on T017 and T019
- T021 depends on everything in the phase

### Parallel opportunities

- T002 with T001
- T006, T007 with T003–T005
- T010, T011, T012 together
- T022, T023, T024 together
- T026, T027 together
- **All of Phase 6** with Phases 3–5
- T032, T033, T034 together

---

## Parallel Example: User Story 1 tests

```bash
# Launch the three test-writing tasks together — different files, no shared state:
Task: "T010 node_selector computed-attribute test in tests/unit/test_computed_attribute.py"
Task: "T011 peering-module happy path in tests/unit/test_clusters.py"
Task: "T012 rendered-manifest structure in tests/unit/test_cilium_manifest.py"
```

## Parallel Example: US4 alongside US1

```bash
# US4 touches only queries/ and .infrahub.yml's queries block — no overlap with the US1 chain:
Task: "T030 ArtifactIDs query in queries/artifact_ids.gql"
Task: "T031 register ArtifactIDs in .infrahub.yml"
```

---

## Implementation Strategy

### MVP first (User Story 1 only)

1. Phase 1 — Setup, and record the clean baseline (T001 matters: FR-009 has no meaning without it)
2. Phase 2 — Foundational, ending at the T009 gate
3. Phase 3 — User Story 1
4. **Stop and validate**: the demo cluster's manifest matches the leaf configs on all three members
5. Demo — this alone delivers the headline value: both halves of every peering from one source

### Incremental delivery

1. Setup + Foundational → schema and typed definitions ready
2. US1 → validate → demo (MVP)
3. US4 → validate → the deployment contract is live (can land alongside US1)
4. US2 → validate → growth and re-placement verified
5. US3 → validate → mixed and empty clusters verified
6. Polish → documentation, ADR judgment, full quickstart walkthrough

### Parallel team strategy

Phase 2 is a single serialised chain ending in a shared regeneration step, so it is poor parallelisation material — one person should own it. After T009:

- Developer A: Phase 3 (US1) — the critical path
- Developer B: Phase 6 (US4), then T032–T034 of Polish
- Once Phase 3 lands, Developer B picks up Phase 4 (US2) and Developer A continues into Phase 5 (US3)

---

## Notes

- **37 tasks total**: Setup 2, Foundational 7, US1 12, US2 4, US3 4, US4 2, Polish 6
- `[P]` = different files, no dependencies on incomplete work
- No integration or contract test tasks, by design — see the Tests note at the top
- Commit after each task or logical group
- The `artifact_name` `Cilium BGP Manifest` and the `ArtifactIDs` query shape are **external contracts**; treat changes to either as breaking
- T021 (existing suite passes with zero edits) is the structural check on FR-009 — if it fails, revise the design rather than the existing tests
