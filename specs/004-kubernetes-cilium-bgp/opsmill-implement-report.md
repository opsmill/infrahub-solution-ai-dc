# Implementation Report: Kubernetes Clusters with Cilium BGP — **INCOMPLETE**

**Feature**: Model Kubernetes Clusters Spanning Multiple Servers and Render Cilium BGP CRDs
**Spec dir**: `specs/004-kubernetes-cilium-bgp`
**Branch**: `dga-004-kubernetes-cilium-bgp`
**Base commit**: `c2b0050`
**Head commit**: `7280000` (plus uncommitted edits to `contracts/graphql-queries.md`, see §6)
**Status**: **INCOMPLETE** — 21 of 37 tasks done; chunks 5–8 and the Phase 6 review never ran.

**Why incomplete**: the run was halted by an **infrastructure block, not a code problem**. The Bash
tool's safety classifier (`claude-sonnet-5[1m]`) became unavailable partway through verifying chunk 4
and stayed unavailable across five consecutive attempts. Every remaining task requires shell access —
running pytest, `inv lint`, and committing — so chunks 5–8 could not be dispatched and the review pass
could not run. Read-only inspection still worked, so chunk 4 was fully reviewed by reading.

Everything committed is lint-clean and test-green as of the last successful verification.

## 1. Environment established during preflight

Preflight surfaced a version conflict that had to be resolved before any work:

| | Version |
|---|---|
| Branch (off `main`) | infrahub-sdk **1.22.0** |
| Stack as found | **1.11.0b0**, Neo4j 2026.05.0 |
| Stack after rebuild | **1.10.5**, Neo4j 2025.10.1 — matches the branch |

The user chose to rebuild the stack from this branch (`inv destroy` → `inv build` → `inv start`),
destroying the previous 1.11.0b0 stack and its data, and to revert the uncommitted `repository.yml`
tweak for a clean tree.

Verified before destroying anything: both base images were pullable, and
`opsmill/infrahub-solution-ai-dc:1.10.5` was already built locally.

**Two facts that matter for any resumed run:**

- `.envrc` is **untracked and gitignored**, and on disk it exports `INFRAHUB_BASE_VERSION=1.11.0b0`,
  while the shell that performed the rebuild held a stale direnv snapshot of `1.10.5`. The running
  stack is therefore **1.10.5**, but a fresh shell reading `.envrc` will target **1.11.0b0** and
  disagree with it. Reconcile `.envrc` before running `inv` commands interactively.
- `INFRAHUB_ADDRESS` is not set anywhere; export `http://localhost:8000` for `infrahubctl`.

## 2. Chunk-by-chunk ledger

| # | Chunk | Tasks | ✅ | ⚠️ | ❌ | Commits |
|---|---|---|---|---|---|---|
| 1 | Phase 1: Setup | 2 (T001–T002) | 2 | 0 | 0 | `61ae83d` (orchestrator fixup) |
| 2 | Phase 2: Foundational | 7 (T003–T009) | 7 | 0 | 0 | `29b3406`, `12f891a` |
| 3 | Phase 3a: US1 peering module | 6 (T010, T011, T013–T016) | 6 | 0 | 0 | `3dea713` |
| 4 | Phase 3b: US1 transform + wiring | 6 (T012, T017–T021) | 6 | 0 | 0 | `7280000` |
| 5 | Phase 4: US2 | 4 (T022–T025) | — | — | — | **not dispatched** |
| 6 | Phase 5: US3 | 4 (T026–T029) | — | — | — | **not dispatched** |
| 7 | Phase 6: US4 | 2 (T030–T031) | — | — | — | **not dispatched** |
| 8 | Phase 7: Polish | 6 (T032–T037) | — | — | — | **not dispatched** |

Orchestrator-authored commits between chunks: `051ed77`, `d722f1e`, and one blockquote-lint fix — all
documentation corrections driven by implementation findings (§6).

### Flagged upward by chunk subagents

**Chunk 1** — `queries/` is **not** a new location: `queries/.gitkeep` was already tracked (commit
`946dbfb`), so `plan.md`'s "the one genuinely new location is `queries/`" was wrong and T002 needed no
work. Also established that `inv test` runs for many minutes because `tests/integration` stands up its
own `infrahub_testcontainers` stack; `pytest tests/unit` is the fast loop. The subagent returned without
committing, so the orchestrator recorded T001 and committed.

**Chunk 2** — Infrahub caps a `description` at **128 characters**; both descriptions `data-model.md`
prescribed were rejected with `string_too_long` and were shortened. Regenerating `protocols.py` against
a real stack discharged a pre-existing debt (the 003 classes had been hand-added offline) but had two
unbudgeted consequences: 42 in-file mypy `[assignment]` errors, suppressed via a per-module override,
and 8 genuine errors in `transforms/cabling_plan.py` whose `type: ignore` comments no longer matched.
All 23 names the repo imports from `protocols.py` were verified to survive.

**Chunk 3** — Chose plain `sorted()` over `netutils.sort_interface_list` for interface ordering.
Verified: `sort_interface_list` raises `ValueError` on `['!!!']` and silently drops `['']`, either of
which would break the module's omit-never-raise contract. (Their report also claimed it raises on
`['1']`; it does not — the core justification still holds.) Also found that `data-model.md` §5's
eligibility check 3 was redundant and unverifiable, and that `ip_address.address.value` has two runtime
shapes (`IPv4Interface` off a node, `str` off raw GraphQL).

**Chunk 4** — Found two omissions in `contracts/graphql-queries.md` §1 that would each have **silently
dropped every member**: no `name { value }` on the server's interfaces (which the ordering sorts on) and
no `id` on the `ip_address` node (a null `id` is how "unset" is detected). Chose to read the query
response through a ~65-line shape adapter rather than re-fetch nodes through the SDK store, because the
store *raises* on a miss — the opposite of omit-never-raise. Added a second, tightly-scoped mypy
override for `yaml` rather than adding `types-PyYAML`, honouring the no-new-dependency gate.

## 3. Tasks not completed

All 16 remaining tasks are still `[ ]`, none because of a code problem — the shell became unavailable:

| Tasks | Chunk | Reason |
|---|---|---|
| T022–T025 | Phase 4 (US2) | Not dispatched — Bash tool unavailable |
| T026–T029 | Phase 5 (US3) | Not dispatched — Bash tool unavailable |
| T030–T031 | Phase 6 (US4) | Not dispatched — Bash tool unavailable |
| T032–T037 | Phase 7 (Polish) | Not dispatched — Bash tool unavailable |

Consequences worth knowing:

- **T028/T029 are load-bearing.** Eligibility filtering (including `layer == "l3"`, so L2 exclusion) and
  omission logging are **not yet implemented**. `clusters.peering_for_member` is the seam. Until T028
  lands, FR-004 is only partly satisfied: incomplete members are omitted because their data is missing,
  but an L2 member with a complete session would *not* be excluded.
- **T030/T031 are unstarted**, so FR-008 (the `ArtifactIDs` query Vidra polls) has no implementation.
- **T037**, the manual quickstart walkthrough that is this feature's only acceptance verification, has
  not run.

## 4. Local-pass evidence

Every test added so far has observed-pass evidence with a verbatim runner line. **No `MISSING` rows** —
the INCOMPLETE status is due to undispatched chunks (§3), not absent evidence.

| Test id | Type | Run command | Passed at (ISO 8601) | Environment | Verbatim pass line |
|---------|------|-------------|----------------------|-------------|--------------------|
| `tests/unit/test_computed_attribute.py::test_node_selector[server-cilium-worker-1-cilium-worker-1]` | unit | `uv run pytest tests/unit/test_clusters.py tests/unit/test_computed_attribute.py -v` | 2026-07-29T19:37:17Z | n/a | `PASSED [ 83%]` |
| `…::test_node_selector[server-web-host-1-web-host-1]` | unit | same | 2026-07-29T19:37:17Z | n/a | `PASSED [ 88%]` |
| `…::test_node_selector[server-server-side-cache-server-side-cache]` | unit | same | 2026-07-29T19:37:17Z | n/a | `PASSED [ 94%]` |
| `…::test_node_selector[cilium-worker-1-cilium-worker-1]` | unit | same | 2026-07-29T19:37:17Z | n/a | `PASSED [100%]` |
| `tests/unit/test_clusters.py::TestBuildCiliumPeerings` (6 tests) | unit | same | 2026-07-29T19:37:17Z | n/a | `PASSED` each; suite `18 passed in 0.04s` |
| `tests/unit/test_clusters.py::TestLeafPortAddress` (2 tests) | unit | same | 2026-07-29T19:37:17Z | n/a | `PASSED` each |
| `tests/unit/test_clusters.py::TestStripPrefixLength` (3 tests) | unit | same | 2026-07-29T19:37:17Z | n/a | `PASSED` each |
| `tests/unit/test_clusters.py::TestInstanceName` (1 test) | unit | same | 2026-07-29T19:37:17Z | n/a | `PASSED` |
| `tests/unit/test_cilium_manifest.py::TestDocumentSet` (4 tests) | unit | `uv run pytest tests/unit/test_cilium_manifest.py -v` | 2026-07-29T19:53:39Z | n/a | `PASSED` each; suite `12 passed in 0.07s` |
| `tests/unit/test_cilium_manifest.py::TestClusterConfig` (4 tests) | unit | same | 2026-07-29T19:53:39Z | n/a | `PASSED` each |
| `tests/unit/test_cilium_manifest.py::TestSharedDocuments` (4 tests) | unit | same | 2026-07-29T19:53:39Z | n/a | `PASSED` each |

**Red-before-green was observed** for chunk 3: `pytest tests/unit/test_clusters.py -q` →
`ModuleNotFoundError: No module named 'infrahub_solution_ai_dc.clusters'` before `clusters.py` existed.

**Whole-suite progression** (each independently re-run by the orchestrator, not just reported):
`107 passed` at baseline → `123 passed in 0.18s` after chunk 3 → `135 passed in 0.23s` after chunk 4.

**FR-009 check**: `uv run pytest tests/unit/test_servers.py tests/unit/test_server_generator.py -q` →
`62 passed in 0.09s` at 2026-07-29T19:53:04Z, with both files confirmed unmodified. Clustering did not
leak into member provisioning.

**Not run locally**: the full `inv test`. `tests/integration` collects 15 tests, **all
`@pytest.mark.skip`-marked**, and stands up its own testcontainers stack. Skipping it is consistent with
the PRD's agreed testing decisions (unit tests only) — see §6.

## 5. Review findings

**Phase 6 (`speckit-review-run`) never ran** — it needs shell access. The findings below come from the
orchestrator's own read-only review of each chunk, so they are not a substitute for that pass.

| Severity | File | Finding | Disposition |
|---|---|---|---|
| Medium | `transforms/cilium_manifest.py` | The `_NodeView`/`_Related`/`_Manager`/`_Absent` adapter (~65 lines) makes parsed GraphQL models impersonate `InfrahubNode`s, and `cluster_members` casts the result to `NetworkServerService` — a lie to the type checker. It is verifiably shape-translation-only (no member decisions), and the rationale is sound, but the cleaner factoring is arguably for `clusters.py` to accept the query model directly. **Deferred** for the real review pass. |
| Low | `src/infrahub_solution_ai_dc/clusters.py:123` | Pyright reports `"Never" is not iterable` on `link.endpoints.peers`, from TypeVar inference through the generic `_related_peer`. mypy (the CI gate) passes, and the behaviour is covered by tests. Pyright is not in CI. **Accepted.** |
| Low | `pyproject.toml` | Two new mypy overrides (`protocols` → `disable_error_code=["assignment"]`; `yaml` → `ignore_missing_imports`). Both are tightly scoped to one module and one code, and each carries a written rationale. **Accepted** — reviewed and judged proportionate. |
| Low | `transforms/cabling_plan.py` | Modified outside its task's stated scope (8 `type: ignore[union-attr]` replaced by 2 `cast`s after the existing kind guard). Semantically identical, covered by 4 passing tests, and forced by T009's mypy gate. **Accepted** — a genuine improvement. |

## 6. Autonomous decisions

1. **Chunk split at T012, not T016/T017.** Phase 3 has 12 tasks, over the ~10 threshold. I split it so
   T012 (the transform's rendered-output test) sits with the transform it exercises. A contiguous split
   would have left chunk 3a holding a test that cannot pass until a later chunk, violating the
   local-pass rule.
2. **Took over T001 myself** after the chunk-1 subagent returned without committing, having stalled ~15
   minutes on `inv test`. Re-dispatching to re-run one command was not worth the wall-clock.
3. **Verified subagent claims rather than trusting them.** Chunk 1's assertion that `queries/.gitkeep`
   was already tracked, and chunk 3's `netutils` justification, were both checked directly. The first
   was right (and exposed an error in my `plan.md`); the second was right in substance with one
   overstated detail.
4. **Corrected four design docs from implementation findings**, committed as they arose:
   `data-model.md` (128-char description cap; redundant eligibility check 3; `peer_name` derivation) and
   `contracts/graphql-queries.md` (the two silently-member-dropping omissions).
5. **`contracts/graphql-queries.md` edits are UNCOMMITTED** — the shell became unavailable before I
   could commit them. They are correct and lint-relevant; commit them on resume.
6. **Did not run the full `inv test`.** The integration suite is entirely skip-marked and stands up its
   own testcontainers stack. This matches the agreed testing decisions, but it means no E2E class was
   exercised locally — recorded here rather than left implicit.
7. **Did not touch `.envrc`.** It is untracked, gitignored, personal to the user, and shared with their
   1.11 work. Its drift from the rebuilt stack is reported in §1 instead.

## 7. Suggested next steps

1. **Re-run `speckit-opsmill-implement` on this spec dir** once the Bash tool is available. It will
   resume at chunk 5 (T022). First commit the pending `contracts/graphql-queries.md` edits so the tree
   is clean, or the preflight will abort on a dirty tree.
2. **Prioritise T028/T029** — L2 exclusion is not yet implemented, so FR-004 is only partly satisfied
   (§3). This is the largest functional gap.
3. **Reconcile `.envrc`** with the rebuilt 1.10.5 stack (§1), or a fresh interactive shell will target
   1.11.0b0 and disagree with what is running.
4. **Run the Phase 6 review pass** (`speckit-review-run`) across `c2b0050..HEAD` — it has not run at all,
   and the medium-severity adapter finding in §5 deserves a second opinion.
5. **Walk `quickstart.md` (T037)** against the stack — it is this feature's only acceptance verification,
   and nothing has validated the feature end to end against real data yet.
