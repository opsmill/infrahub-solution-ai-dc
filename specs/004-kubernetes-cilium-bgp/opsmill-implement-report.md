# Implementation Report: Kubernetes Clusters with Cilium BGP — **INCOMPLETE**

**Feature**: Model Kubernetes Clusters Spanning Multiple Servers and Render Cilium BGP CRDs
**Spec dir**: `specs/004-kubernetes-cilium-bgp`
**Branch**: `dga-004-kubernetes-cilium-bgp` (based on `main`)
**Base commit**: `c2b0050` · **Head commit**: `86d90e7`
**Status**: **INCOMPLETE** — **36 of 37 tasks done.** All code, schema, seed data, wiring, tests and
documentation are complete and green. What remains is **T037**, the live `quickstart.md` acceptance
walkthrough, plus the implement skill's own Phase 6 review pass.

Ran across two sessions; the first halted at 21/37 when the shell became unavailable, the second
completed chunks 5–8a.

**Verification state at head**: `uv run pytest tests/unit -q` → **199 passed**;
`uv run inv lint` → rumdl, yamllint, `ruff check` and `mypy .` (strict) all clean.

## 1. Environment

Preflight found the branch and the running stack on different Infrahub versions. The user chose to
rebuild the stack from this branch, destroying the previous 1.11.0b0 stack and its data.

| | Version |
|---|---|
| Branch (off `main`) | infrahub-sdk **1.22.0** |
| Stack as found | 1.11.0b0, Neo4j 2026.05.0 |
| Stack after rebuild | **1.10.5**, Neo4j 2025.10.1 — matches the branch |

**Two facts that matter for anyone resuming:**

- `.envrc` is **untracked and gitignored** and exports `INFRAHUB_BASE_VERSION=1.11.0b0`, while the shell
  that rebuilt held a stale direnv snapshot of `1.10.5`. The running stack is **1.10.5**, so a fresh
  shell reading `.envrc` will disagree with it. Reconcile before running `inv` commands interactively.
- `INFRAHUB_ADDRESS` is set nowhere; export `http://localhost:8000` for `infrahubctl`.
- The stack has the **schema** loaded but **no objects** — `CoreArtifact` count is 0. Nothing has been
  rendered against real data. This is exactly what T037 would have done.

## 2. Chunk-by-chunk ledger

| # | Chunk | Tasks | ✅ | ⚠️ | ❌ | Commits |
|---|---|---|---|---|---|---|
| 1 | Phase 1: Setup | 2 (T001–T002) | 2 | 0 | 0 | `61ae83d` (orchestrator fixup) |
| 2 | Phase 2: Foundational | 7 (T003–T009) | 7 | 0 | 0 | `29b3406`, `12f891a` |
| 3 | Phase 3a: US1 peering module | 6 (T010, T011, T013–T016) | 6 | 0 | 0 | `3dea713` |
| 4 | Phase 3b: US1 transform + wiring | 6 (T012, T017–T021) | 6 | 0 | 0 | `7280000` |
| 5 | Phase 4: US2 | 4 (T022–T025) | 4 | 0 | 0 | `76e52d0` |
| 6 | Phase 5: US3 | 4 (T026–T029) | 4 | 0 | 0 | `b0f4620` |
| 7 | Phase 6: US4 | 2 (T030–T031) | 2 | 0 | 0 | `8b56b42` |
| 8a | Phase 7: Polish (docs) | 5 (T032–T036) | 5 | 0 | 0 | `df58a5e` |
| 8b | Phase 7: Polish (acceptance) | 1 (T037) | 0 | 0 | 1 | **not dispatched** |

Orchestrator-authored commits between chunks: `051ed77`, `d722f1e`, `c50d216`, `0f54687`, `86d90e7` —
documentation corrections driven by implementation findings, plus the `CLAUDE.md` active-features entry.

### Flagged upward by chunk subagents

**Chunk 1** — `queries/` is **not** a new location: `queries/.gitkeep` was already tracked (`946dbfb`),
so `plan.md`'s claim that it was the one genuinely new directory was wrong and T002 needed no work. Also
established that `inv test` runs for minutes because `tests/integration` stands up its own
`infrahub_testcontainers` stack; `pytest tests/unit` is the fast loop. The subagent returned without
committing, so the orchestrator recorded T001 and committed.

**Chunk 2** — Infrahub caps a `description` at **128 characters**; both descriptions `data-model.md`
prescribed were rejected with `string_too_long` and were shortened. Regenerating `protocols.py` against
a real stack discharged a pre-existing debt (the feature-003 classes had been hand-added offline) but had
two unbudgeted consequences: 42 in-file mypy `[assignment]` errors, suppressed by a per-module override,
and 8 genuine errors in `transforms/cabling_plan.py` whose `type: ignore` comments no longer matched. All
23 names the repo imports from `protocols.py` were verified to survive.

**Chunk 3** — Chose plain `sorted()` over `netutils.sort_interface_list` for interface ordering.
Verified: `sort_interface_list` raises `ValueError` on `['!!!']` and silently drops `['']`, either of
which would break the module's omit-never-raise contract. Also found `data-model.md` §5's eligibility
check 3 redundant and unverifiable, and that `ip_address.address.value` has two runtime shapes
(`IPv4Interface` off a node, `str` off raw GraphQL).

**Chunk 4** — Found two omissions in `contracts/graphql-queries.md` §1 that would each have **silently
dropped every member**: no `name { value }` on the server's interfaces (which the ordering sorts on) and
no `id` on the `ip_address` node (a null `id` is how "unset" is detected). Chose to read the query
response through a shape adapter rather than re-fetch through the SDK store, because the store *raises*
on a miss — the opposite of omit-never-raise.

**Chunk 5** — No new test failed; the pure-function property holds as `research.md` R7 claims. Guarded
against vacuous tests with two temporary mutations (dropping `sorted()`, flipping the leaf-kind
constant), each observed to fail the right test, then reverted. Also repaired four `MD056` table errors
the orchestrator had introduced in an earlier version of this report, which had left `inv lint` red.

**Chunk 6 — the largest functional gap, now closed.** `layer == "l3"` filtering was genuinely missing, so
**an L2 member with a complete session was being rendered into the manifest**. Observed RED before the
fix (`assert 3 == 2`, and the L2 selector present in the body), GREEN after. The four missing-data checks
were already present. Omission logging added via an optional `logger` parameter, keeping the module pure
and silent by default.

**Chunk 7** — Added a **negative control** so "no GraphQL errors" means something: a bogus field selection
does return an `errors` key, and the documented silent failure (`String` + `name__value`) was reproduced
as an empty edge list with no error. The stack has zero artifacts, so the four fields could not be
observed non-null — reported plainly rather than implied.

**Chunk 8a** — Judged that the one-cluster-config-per-member decision **does** warrant an ADR and wrote
`dev/adr/0007`, on the grounds that it has a real rejected alternative refused by a *verified external*
constraint. Reported two stale things it deliberately did not fix; the orchestrator fixed one
(`CLAUDE.md` active features) and the other (`CONTEXT.md`'s opening scope paragraph) remains open.

## 3. Tasks not completed

| Task | Reason |
|---|---|
| T037 — walk `quickstart.md` end to end and tick its Success checklist | Not dispatched. The dispatch was interrupted by the user before it ran. |

**What T037's absence means.** It is this feature's **only** acceptance verification — the PRD's agreed
testing decisions deliberately exclude integration tests, so nothing else exercises the feature against
real data. Concretely, the following are **implemented and unit-tested but never observed end to end**:

- The artifact rendering for a real cluster with real generated members (FR-003, SC-002, SC-004). The
  manifest has never been produced from live Infrahub data — only from fixtures.
- That the leaf-side startup config and the cluster-side manifest actually agree on ASNs and addresses.
  Unit tests prove the manifest is a correct function of the session data; they cannot prove the two
  artifacts agree in a running system.
- FR-006's **trigger half** — that Infrahub re-renders the artifact on add / remove / move. Unit tests
  cover only that the manifest is a function of its members.
- FR-008 against a real artifact. The `ArtifactIDs` query is registered and verified schema-valid, but
  with zero artifacts on the stack its four fields were never seen non-null.
- Whether an empty manifest causes Vidra to withdraw previously-applied peering (critique finding P3,
  recorded in `spec.md` as an explicit unverified assumption).

Also outstanding: the implement skill's **Phase 6 review pass** (`speckit-review-run`) never ran.

## 4. Local-pass evidence

Every test added by this run has an observed pass with a verbatim runner line. **No `MISSING` rows.**

| Test id | Type | Run command | Passed at (ISO 8601) | Environment | Verbatim pass line |
|---------|------|-------------|----------------------|-------------|--------------------|
| `test_computed_attribute.py::test_node_selector` (4 parametrized cases) | unit | `uv run pytest tests/unit/test_clusters.py tests/unit/test_computed_attribute.py -v` | 2026-07-29T19:37:17Z | n/a | `PASSED` each; suite `18 passed in 0.04s` |
| `test_clusters.py::TestBuildCiliumPeerings` (6) | unit | same | 2026-07-29T19:37:17Z | n/a | `PASSED` each |
| `test_clusters.py::TestLeafPortAddress` (2) | unit | same | 2026-07-29T19:37:17Z | n/a | `PASSED` each |
| `test_clusters.py::TestStripPrefixLength` (3) | unit | same | 2026-07-29T19:37:17Z | n/a | `PASSED` each |
| `test_clusters.py::TestInstanceName` (1) | unit | same | 2026-07-29T19:37:17Z | n/a | `PASSED` |
| `test_cilium_manifest.py::TestDocumentSet` (4) | unit | `uv run pytest tests/unit/test_cilium_manifest.py -v` | 2026-07-29T19:53:39Z | n/a | `PASSED` each; suite `12 passed in 0.07s` |
| `test_cilium_manifest.py::TestClusterConfig` (4) | unit | same | 2026-07-29T19:53:39Z | n/a | `PASSED` each |
| `test_cilium_manifest.py::TestSharedDocuments` (4) | unit | same | 2026-07-29T19:53:39Z | n/a | `PASSED` each |
| `test_cilium_manifest.py::TestMemberCountDifferencing` (3) | unit | `uv run pytest -v <six node ids>` | 2026-07-30T04:46:11Z | n/a | `PASSED` each; suite `6 passed in 0.04s` |
| `test_cilium_manifest.py::TestMemberMove` (2) | unit | same | 2026-07-30T04:46:11Z | n/a | `PASSED` each |
| `test_clusters.py::TestBuildCiliumPeerings::test_shuffled_input_order_yields_identical_records` | unit | same | 2026-07-30T04:46:11Z | n/a | `PASSED [100%]` |
| `test_clusters.py::TestEligibility` (22, parametrized over 10 ineligible shapes) | unit | `uv run pytest tests/unit/test_clusters.py -v -k "TestEligibility or TestOmissionLogging"` | 2026-07-30T04:59:28Z | n/a | `PASSED` each; suite `45 passed, 13 deselected in 0.04s` |
| `test_clusters.py::TestOmissionLogging` (23) | unit | same | 2026-07-30T04:59:28Z | n/a | `PASSED` each |
| `test_cilium_manifest.py::TestMixedCluster` (4) | unit | `uv run pytest tests/unit/test_cilium_manifest.py -v -k "TestMixedCluster or TestIncompleteMember or TestEmptyCluster"` | 2026-07-30T04:59:38Z | n/a | `PASSED` each; suite `13 passed, 17 deselected in 0.04s` |
| `test_cilium_manifest.py::TestIncompleteMember` (3) | unit | same | 2026-07-30T04:59:38Z | n/a | `PASSED` each |
| `test_cilium_manifest.py::TestEmptyCluster` (6) | unit | same | 2026-07-30T04:59:38Z | n/a | `PASSED` each |

**Red-before-green observed twice**, both recorded verbatim: chunk 3
(`ModuleNotFoundError: No module named 'infrahub_solution_ai_dc.clusters'`) and chunk 6
(`AssertionError: assert 3 == 2` plus the L2 selector present in the body).

**Full-suite progression**, each independently re-run by the orchestrator rather than taken on report:
`107` (baseline) → `123` → `135` → `141` → **`199 passed in 0.21s`**.

**FR-009 check**: `uv run pytest tests/unit/test_servers.py tests/unit/test_server_generator.py -q` →
`62 passed in 0.09s`, both files confirmed unmodified. Clustering did not leak into member provisioning.

**No integration or E2E tests were added, by design** — the PRD's agreed testing decisions exclude them.
The consequence is that acceptance rests entirely on T037, which did not run (§3).

> **Correction (measured in CI, 2026-07-30).** This section originally justified that with
> "`tests/integration` is entirely `@pytest.mark.skip`-marked". **That was wrong** — I inferred it from
> `grep` hit counts (one hit was a docstring mentioning the marker, not applying it) and never ran the
> suite. CI's `integration-test` job runs `pytest tests/` and reports **215 passed, 6 skipped**: of 15
> integration tests, **9 genuinely pass** against a real testcontainers stack. The claim propagated into
> `plan.md`, `research.md` R6b, `tasks.md` and every subagent briefing in this run; all are now corrected.
>
> The decision itself stands — it was agreed in the source PRD, and the specific Server service journeys
> this feature would have mirrored are among the 6 skipped. But the stated ground for it was too broad.

## 5. Review findings

**The implement skill's Phase 6 review pass never ran.** The findings below are the orchestrator's own
read-only review of each chunk, and are not a substitute for it.

| Severity | File | Finding | Disposition |
|---|---|---|---|
| Medium | `transforms/cilium_manifest.py` | The `_NodeView`/`_Related`/`_Manager`/`_Absent` adapter makes parsed GraphQL models impersonate `InfrahubNode`s, and `cluster_members` casts the result to `NetworkServerService` — a lie to the type checker. Verifiably shape-translation-only, with sound rationale, but having `clusters.py` accept the query model directly is arguably cleaner. | Deferred to a real review pass |
| Low | `src/infrahub_solution_ai_dc/clusters.py` | Pyright reports `"Never" is not iterable` on `link.endpoints.peers`, from TypeVar inference through the generic `_related_peer`. mypy — the CI gate — passes, and the behaviour is covered by tests. Pyright is not in CI. | Accepted |
| Low | `pyproject.toml` | Two new mypy overrides (`protocols` → `disable_error_code=["assignment"]`; `yaml` → `ignore_missing_imports`). Each is scoped to one module, and each carries a written rationale. | Accepted as proportionate |
| Low | `transforms/cabling_plan.py` | Modified outside its task's stated scope: 8 `type: ignore[union-attr]` replaced by 2 `cast`s after the existing kind guard. Semantically identical, covered by 4 passing tests, forced by T009's mypy gate. | Accepted — a genuine improvement |
| Low | `CONTEXT.md` | Its opening paragraph still scopes the document to "fabric + EVPN/VXLAN overlay", now understated given server attachment and clustering. Flagged by chunk 8a, deliberately not fixed. | Open |

## 6. Autonomous decisions

1. **Split Phase 3 at T012, not at T016/T017.** Phase 3 had 12 tasks, over the ~10 threshold. T012 tests
   the transform built in T019, so a contiguous split would have left a chunk holding a test that could
   not pass, violating the local-pass rule.
2. **Split Phase 7 into 8a (docs, T032–T036) and 8b (T037).** T037 needs live data loaded; isolating it
   meant a stack problem could not lose the documentation deliverables. 8b was then interrupted.
3. **Took over T001 directly** after the chunk-1 subagent stalled ~15 minutes on `inv test` and returned
   without committing.
4. **Verified subagent claims rather than trusting them.** Notably: chunk 1's `queries/.gitkeep` claim
   (correct — and it exposed an error in `plan.md`), chunk 3's `netutils` justification (correct in
   substance, one detail overstated), chunk 6's L2 exclusion (re-verified end to end by rendering a
   mixed cluster whose L2 member had a *complete* session), and a diagnostics alarm about a half-applied
   `_omit`/`_omitted` rename that proved to be a stale mid-edit snapshot.
5. **Corrected five design/context docs from implementation findings** as they arose, rather than letting
   the specs drift from the code: `data-model.md` (×3), `contracts/graphql-queries.md`, `CLAUDE.md`.
6. **Did not run the full `inv test`.** It stands up its own testcontainers stack and takes ~13 minutes,
   so every local gate in this run used `pytest tests/unit`. Two costs surfaced later, both in CI: the
   integration suite is **not** entirely skip-marked as I had claimed (9 of 15 pass — see §4), and
   `inv lint` does not run `ruff format --check`, so a formatting drift reached CI and failed
   `python-lint` on both 3.11 and 3.14. Fixed in `7c99880`.
7. **Did not touch `.envrc`.** Untracked, gitignored, personal to the user, and shared with their 1.11
   work. Its drift from the rebuilt stack is reported in §1 instead.

## 7. Suggested next steps

1. **Run T037** — walk `quickstart.md` end to end. It needs `inv load` to populate the stack, and it is
   the only acceptance verification this feature has (§3). Until it runs, the feature is unproven against
   real data even though every unit test passes.
2. **Run the Phase 6 review pass** (`speckit-review-run`) across `c2b0050..HEAD`; the medium-severity
   adapter finding in §5 deserves an independent opinion.
3. **Reconcile `.envrc`** with the rebuilt 1.10.5 stack (§1).
4. **Close the `CONTEXT.md` scope-paragraph gap** noted in §5.
