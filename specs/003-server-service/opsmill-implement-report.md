# Implementation Report: Connect L2/L3 Servers to Leaves via a Server Service

**Status: INCOMPLETE** — all code chunks implemented, unit-tested, lint-clean, and committed; 6 stack-gated
validation tasks (schema-load, integration, E2E) are deferred because no dedicated Infrahub stack is
available in this worktree. See §3 and §7.

## 1. Header

| Field | Value |
|-------|-------|
| Feature | Connect L2/L3 Servers to Leaves via a Server Service (`003-server-service`) |
| Spec dir | `specs/003-server-service` |
| Base commit (HEAD at start) | `cefa294` |
| Head commit (after review) | `8c01bb3` |
| Feature commits | 9 (`7847d7d` … `8c01bb3`) |
| Diff | ~2050 insertions across 26 files (10 code/schema/objects, 3 templates, 2 test files, 1 doc, spec docs) |
| Unit tests | **69 passed** (baseline 44 + 25 new) |
| Wall-clock | not precisely tracked (8 implement subagents + 6 review + 1 fix subagent, run sequentially/parallel-review) |
| Environment caveat | No Infrahub stack for this worktree (an unrelated `testing-rate-limiting-*` compose project is up); schema-load / integration / E2E not runnable locally |

## 2. Chunk-by-chunk ledger

| # | Chunk (phase) | Tasks | ✅ | ⚠️ | ❌ | Commit | Flagged upward |
|---|---------------|-------|----|----|----|--------|----------------|
| 1 | Phase 1 Setup (orchestrator inline) | T001–T002 | 2 | 0 | 0 | `7847d7d` | Ran `uv sync`; baseline 44 unit tests green |
| 2 | Phase 2 Schema & types | T003–T010 | 6 | 2 | 0 | `a6041fb` | T008 protocols hand-added (needs stack regen); T009 deferred; NetworkDevice reconciled to inherit the generic; single uniqueness `[device, server, name]`; **hfid gap** for null-device server ports |
| 3 | Phase 2 Pools/groups/helpers/pod-pool/menu | T011–T016 | 6 | 0 | 0 | `06c2fa1` | Server /31 supernet = `192.168.0.0/16` (/24 per pod); helpers return `None` (generator raises); fixed `protocols.py` `NetworkPod.server_prefix_pool` omission |
| 4 | Phase 3 US1 generator core | T017–T022 | 6 | 0 | 0 | `2e129b7` | Server port identity via `server` rel + name (not hfid); T020 needed no change (RackGen has no checksum, PodGen hashes only its own nodes); L2/US3 extension seams left |
| 5a | Phase 3 US1 config rendering | T023–T026 | 4 | 0 | 0 | `a8251d6` | NOS-syntax choices for ipv4_unicast neighbor; offline Jinja render matched the contract |
| 5b | Phase 3 US1 seed + tests + validate | T027–T030 | 3 | 1 | 0 | `55a081f` | T028 = 13 unit tests (real pass); T029 integration written + skip-gated; T030 deferred; fail-loud *raises* live in async generator (integration-only) |
| 6 | Phase 4 US2 L2 server | T031–T035 | 4 | 1 | 0 | `b52ad8e` | `validate_service` is pure/unit-testable (+5 tests); SD8 kept as v1 option (a); T035 deferred |
| 7 | Phase 5 US3 explicit placement | T036–T038 | 2 | 1 | 0 | `bf89eb7` | Pure/async validation split (+5 tests); last-free-port determinism relied on write-side uniqueness (later found NOT enforced — see §5); T038 deferred |
| 8 | Phase 6 Polish | T039–T042 | 2 | 2 | 0 | `f4f8734` | Feature note at `dev/guides/connect-servers.md`; T040/T042 partial (unit green, integration/E2E deferred) |
| — | Review remediation (Phase 6 fixes) | 10 fixes | — | — | — | `8c01bb3` | See §5; 69 unit tests green after |

No chunk was ❌ blocked; none required a retry.

## 3. Tasks not completed

All 6 are **environment-gated validation tasks** (they require `inv load-schema` / `inv start` / a Dockerized
Infrahub, which is not available in this worktree). The corresponding **code** is complete and committed; only
the live verification is deferred. Each is annotated inline in `tasks.md` with a runbook.

| Task | What it validates | Why deferred |
|------|-------------------|--------------|
| T009 | Schema converges via `inv load-schema` | Needs running Infrahub. Offline proxy passed (`infrahubctl protocols` parsed all schemas; YAML valid) |
| T030 | US1 L3 E2E (server cabled, /31 both ends, ASN, paired sessions, rendered leaf config, idempotent re-run) | Needs `inv load` + `inv start` |
| T035 | US2 L2 E2E (Segment `racks` grows, no BGP/IP) | Needs stack |
| T038 | US3 E2E (explicit placement honored; every fail-loud path creates no partial objects) | Needs stack |
| T040 | Full `inv test` (unit **+** integration) | Unit green (69); integration is skip-gated (no stack) |
| T042 | Full quickstart §1–8 | §1–2 offline done; §3–8 need stack |

**Runbook to finish** (on a machine with a dedicated stack): `inv load` → `inv start`; regenerate
`protocols.py` against the loaded schema (replaces the hand-added classes); lift the `@pytest.mark.skip`
markers in `tests/integration/test_server_service.py` and run `uv run pytest tests/integration/test_server_service.py`; then walk quickstart §3–8.

## 4. Local-pass evidence

All unit tests were observed to PASS locally. Environment for every row: `uv`-synced `.venv`, Python 3.12.13,
pytest 8.4.1, worktree `dga/feat-server-cilium-r9uuo`, **no Infrahub stack**. Per-test `PASSED` lines were
captured verbatim in each chunk's subagent report; rows are grouped by test class (cohesive behavior).

| Test id | Type | Run command | Passed at (ISO 8601) | Env | Verbatim pass line |
|---------|------|-------------|----------------------|-----|--------------------|
| `test_servers.py::TestSelectLeastUtilizedRack` (6 incl. SC-005 even-spread) | unit | `uv run pytest tests/unit/test_servers.py -v` | 2026-07-20T08:17:44Z | .venv, no stack | `25 passed in 0.02s` |
| `test_servers.py::TestSelectFreeServerPort` (6) | unit | `uv run pytest tests/unit/test_servers.py -v` | 2026-07-20T08:17:44Z | .venv, no stack | `25 passed in 0.02s` |
| `test_servers.py::TestUpsertEbgpSession` (2) | unit | `uv run pytest tests/unit/test_servers.py -v` | 2026-07-20T07:45:33Z | .venv, no stack | `13 passed` (T028 run) |
| `test_servers.py::TestValidateService` (5) | unit | `uv run pytest tests/unit/test_servers.py::TestValidateService -v` | 2026-07-20T07:51:28Z | .venv, no stack | `5 passed in 0.01s` |
| `test_servers.py::TestValidateExplicitPort` (5) | unit | `uv run pytest tests/unit/test_servers.py -v` | 2026-07-20T07:58:03Z | .venv, no stack | `23 passed in 0.02s` |
| `test_servers.py::TestRequireAllocated` (2) | unit | `uv run pytest tests/unit/test_servers.py -v` | 2026-07-20T08:17:44Z | .venv, no stack | `25 passed in 0.02s` |
| **Full unit suite** (`tests/unit/`, 69 tests) | unit | `uv run pytest tests/unit/ -q` | 2026-07-20T08:17:51Z | .venv, no stack | `69 passed in 0.04s` |
| `test_server_service.py::TestServerServiceL3::{test_l3_server_journey, test_rerun_is_empty_diff, test_l2_server_journey, test_explicit_placement_honored, test_explicit_occupied_port_fails_loud}` (5) | integration/e2e | `uv run pytest tests/integration/test_server_service.py` | deferred — local E2E not supported | requires Dockerized Infrahub stack | `@pytest.mark.skip`; collects (8 tests) but journeys not runnable locally |

No `MISSING` rows. The integration/E2E rows are `deferred — local E2E not supported` (flagged in §6), which
per the workflow does not block; but the deferred *tasks* (§3) make the overall run INCOMPLETE.

## 5. Review findings

Six specialized reviewers (code, errors, tests, types, comments, simplify) ran across `cefa294..HEAD`.
**No CRITICAL.** Fixed-inline items are in commit `8c01bb3`; deferred items need a running stack or a
broad-blast-radius schema change and are recorded for follow-up.

| Sev | Area | File | Finding | Disposition |
|-----|------|------|---------|-------------|
| HIGH | tests | `generate_server.py` (allocate_server_asn) | Pool-exhaustion fail-loud untested (spec-promised) | **Fixed** — extracted pure `require_allocated()` guard + unit tests |
| HIGH | tests | `servers.py` | SC-005 even-spread had zero coverage | **Fixed** — added `test_repeated_placement_spreads_evenly` |
| HIGH | errors | `generate_server.py` (~155-163) | Docstring falsely claimed write-side uniqueness makes last-free-port contention fail loud; `NetworkLink.endpoints` has no uniqueness constraint, so a racer silently re-points `leaf_port.link` | **Partially fixed** — docstring corrected to state it is NOT enforced; **enforcement deferred** (needs endpoint uniqueness constraint + stack) |
| HIGH | types | `schemas/device.yml` | `NetworkInterface.human_friendly_id` `[device__hostname, name]` doesn't resolve for null-device server ports; non-generator HFID upserts would misbehave | **Deferred** — generator already works around it; safe HFID redesign needs schema convergence testing on a stack |
| HIGH | types | `schemas/device.yml` | No XOR invariant: `device`+`server` both optional Parent → illegal states representable | **Partially fixed** — schema `description` documents the exactly-one-owner invariant (Infrahub can't express XOR; generator never creates the bad state); check-guard deferred |
| MED | code | `startup_config_*.j2` | L3 eBGP neighbor rendered in global BGP instance, not the tenant VRF | **Deferred** — functional rendering, needs stack to validate; possibly SD9 v1 scope |
| MED | errors | `generate_server.py` (configure_l3) | Some L3 precondition reads happen after the server/port/ASN are written → weakens "no partial objects" | **Deferred** — generator-flow reorder; not integration-testable locally |
| MED | errors | `generate_server.py` (generate) | Bare `assert` on external query data (stripped under `-O`) | **Deferred** — recommend `ValueError` per vendors convention |
| MED | code | `generate_server.py` (select_rack) | Server-count query fetched instance-wide | **Fixed** — scoped with `rack__ids=fabric_rack_ids` |
| MED | comments | `generate_server.py` (resolve_overlay_asn) | Docstring inverted ("leaf-side remote AS") | **Fixed** |
| MED | tests | `test_server_service.py` (occupied-port) | Assertion may pass vacuously (asserts absence without confirming the run errored) | **Deferred** — skip-gated; tighten when stack available |
| LOW | comments | `protocols.py` | Hand-added banner omitted `NetworkPod.server_prefix_pool` | **Fixed** |
| LOW | code | `startup_config_*.j2` | Could emit malformed `neighbor  remote-as N` if peer IP unresolved | **Fixed** — `{% if sns.addr %}` guard |
| LOW | tests | `test_servers.py` | Mislabeled/duplicate test under `TestValidateExplicitPort` | **Fixed** — removed duplicate |
| LOW | code | `generate_server.py` | Dead `layer="l3"` default | **Not changed** — query model types `layer` as `str \| None`, so the fallback is reachable for mypy; removing breaks strict typing |
| LOW/advisory | simplify | `startup_config_*.j2` | Peer-IP scan loop duplicated 4×; consider a computed attr / macro | **Deferred** (advisory) |
| LOW | types | `schemas/routing.yml` | `BGPPeer.hostname` now globally unique across devices+servers; server ASN > signed-32-bit | **Recorded** — confirm `server-<name>` can't collide + Number is 64-bit (verify on stack) |

## 6. Autonomous decisions (worth revisiting)

1. **Phase 1 handled inline by the orchestrator** (not a subagent) — `uv sync` + branch check are environment prep, not feature code; committed as `7847d7d`.
2. **`protocols.py` hand-added** (T008) instead of a stack regen, because no dedicated stack exists — required so downstream code imports and mypy-strict passes. A banner in the file + `tasks.md` flag it; **it must be regenerated against a loaded schema before merge.**
3. **Server-ASN pool made a single global `CoreNumberPool`** (32-bit private range) rather than per-Pod as the PRD listed — a `CoreNumberPool` binds to one (node, attribute); documented in `research.md` SD6.
4. **Server /31 supernet chosen as `192.168.0.0/16`** (only RFC1918 block not already used by underlay 10/8 or overlay 172.16/16).
5. **Integration/E2E tests are `@pytest.mark.skip`-gated and deferred** — this worktree has no dedicated Infrahub stack and must not compete with the unrelated running stack. Evidence marked `deferred — local E2E not supported`.
6. **Review-fix triage**: fixed only the safe, unit-testable/doc-level HIGH+ findings inline; deferred the ones that change generator control-flow or schema structure, because without a stack I cannot verify they don't regress **idempotency (SC-003)** or **schema convergence** — a worse outcome than the recorded gap. The most notable deferral is the **last-free-port contention enforcement** (needs a uniqueness constraint on `NetworkLink.endpoints`, validated on a stack).
7. **SD8 (L2) kept as v1 option (a)** — adding a Rack to `Segment.racks` does not auto-re-trigger the OverlayGenerator; overlay materialization remains a separate step.

## 7. Suggested next steps

1. **On a machine with a dedicated Infrahub stack** (highest priority — clears all 6 deferred tasks):
   - `inv load` → `inv start`; **regenerate `src/infrahub_solution_ai_dc/protocols.py`** against the loaded schema (replacing the hand-added classes) and confirm no diff in intent.
   - Run `inv load-schema` (T009), lift the `@pytest.mark.skip`s and run `uv run pytest tests/integration/test_server_service.py` (T040), then walk quickstart §3–8 (T030/T035/T038/T042). Tick the boxes as they pass.
2. **Address the deferred HIGH review findings** (need the stack): add a uniqueness constraint enforcing single-cabling on `NetworkLink.endpoints` (contention), and decide the `NetworkInterface.human_friendly_id` treatment for server ports.
3. **Decide the eBGP-in-VRF question** (MED): confirm whether the L3 server neighbor should render inside the tenant VRF address-family or is intentionally global for v1.
4. **Then**: `/opsmill-dev-pr` to open the PR (do not push from here — the workflow stops before PR).

*Report generated at Phase 7 of `speckit-opsmill-implement`. Head commit `8c01bb3`.*
