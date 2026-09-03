# Implementation Report: NVIDIA Cumulus Linux Vendor Support

**Spec dir**: `specs/006-cumulus-vendor-support/`
**Base commit** (prep complete, before implementation): `b171177`
**Head commit**: `df57b4b` (updated after a live-stack closure session; original implementation-only head was
`8f69edf`)
**Branch**: `main` (no dedicated feature branch was created for this feature — every commit, including the
prep-phase specs, was made directly on `main`, consistent with how `specs/005-sonic-vendor-support` was also
committed)
**Total tasks**: 36 (T001-T036) — **35 done, 1 not completed** (see §3)
**Wall-clock**: ~40 minutes of implementation/review (4 subagent dispatches) + ~35 minutes of live-stack
closure once Docker became available in this environment

---

## 1. Chunk-by-chunk ledger

### Chunk 1 — Setup + Foundational (T001-T008)

- Tasks: 8 (`uv sync`; `vendors.py` allow-list; `test_vendors.py` happy-path case; `cumulus_devices` group;
  `Cumulus` manufacturer; 4 device types; 8 device templates; new
  `tests/unit/test_cumulus_device_templates.py`)
- Outcome: **8 ✅ done**, 0 ⚠️, 0 ❌
- Commit: `84d903a` — "feat(cumulus): add vendor plumbing and device templates (T001-T008)"
- Flagged upward: no `006-cumulus-vendor-support` git branch exists (prep commits were already on `main`); the
  subagent proceeded on `main` per explicit instruction rather than creating one, matching this feature's
  established pattern.

### Chunk 2 — Template, registration, demo fabric (T009-T017)

- Tasks: 9 (`startup_config_cumulus.j2` preamble/interfaces/FRR/tenant-overlay sections, banner comments;
  `.infrahub.yml` registration; `Fabric-F`/`Pod-F1-3`; 8 `Fabric-F` racks; `Amber` tenant/VRF/segments)
- Outcome: **9 ✅ done**, 0 ⚠️, 0 ❌
- Commit: `ef6a3f2` — "feat(cumulus): add startup-config template, registration, demo fabric (T009-T017)"
- Flagged upward: no template bugs found during the required synthetic Jinja2 render (leaf + spine/RR mock
  data, using the SDK's actual `trim_blocks=True, lstrip_blocks=True` environment) — attributed to copying the
  SONiC-precedent structure (D13 lessons) deliberately from the start rather than needing its own bug-fix pass.

### Chunk 3 — Documentation & polish (T026-T032)

- Tasks: 7 (`CONTEXT.md`, `AGENTS.md`, `CLAUDE.md`, `README.md`, five `docs/docs/solution-ai-dc/*.mdx` pages,
  Vale spelling-exceptions, Vale run)
- Outcome: **7 ✅ done**, 0 ⚠️, 0 ❌
- Commit: `10393f1` — "docs(cumulus): update agent/human-facing docs and Vale exceptions (T026-T032)"
- Flagged upward: Vale itself (not just `inv lint`, which doesn't cover Markdown) was actually downloaded and
  run locally (v3.13.0, matching CI) — 0 errors/16 warnings before and after, so T031/T032 have real
  verification, not just "added the exception entries and hoped."

### Orchestrator fixups — T018, T033, and blocking T019-T025/T034-T036

Not dispatched to a subagent — performed directly, since these either required no code change (verification
only) or could not proceed at all in this sandbox:

- **T018** ✅ confirmed directly: `inv lint` clean; `pytest tests/unit -q` → 311 passed; `pytest
  tests/integration -q` → 25 errors, all pre-existing "no Docker daemon" failures unrelated to this feature.
- **T033** ✅ confirmed directly: `git diff --stat main -- schemas/ generators/` is empty across all feature
  commits — SC-002 holds.
- **T019-T025, T034-T035** ❌ blocked — `docker info` fails in this sandbox; every one of these requires a live
  Infrahub stack (`inv start && inv load`, generation, artifact inspection). See §3.
- **T036** — not started; requires a human Cumulus Linux/FRR reviewer, which cannot be performed or simulated
  by an agent. See §3.
- Commit: `b98f95a` — "test(cumulus): confirm T018/T033, block T019-T025/T034-T035 on Docker"

### Review pass (Phase 6)

Four parallel `general-purpose` subagents, each invoking one `speckit-review-*` skill (code, tests, comments,
errors) against `git diff b171177 HEAD`. `types` was not run (no new type design in this feature — the only
Python change is a one-line tuple addition plus a new test file); `simplify` was not run given the four
substantive passes returned essentially clean.

- **code**: 0 Critical / 0 Important / 0 Suggestion. Verified all 8 contract acceptance rules (A1-A8) by
  rendering the actual template through the SDK's real Jinja environment settings against multiple synthetic
  device contexts, and confirmed all four SONiC D13-class defects were avoided from the start.
- **tests**: 0 Critical / 0 Important / 0 Suggestion. Confirmed `test_cumulus_device_templates.py` is a
  structurally faithful, non-weaker mirror of `test_sonic_device_templates.py`, and its expected-value tables
  match `data-model.md` §4 and the actual YAML (not just internally self-consistent).
- **comments/docs**: 0 Critical / 0 Important / **1 Suggestion** (cosmetic — `evpn-vxlan-overlay.mdx` could
  name "ifupdown2" explicitly for parity with the template's own banner comment). Not applied — cosmetic,
  non-blocking, and the current wording is not inaccurate.
- **errors**: 0 Critical / **1 Important** / 1 Suggestion (no automated Jinja2 render test exists for the new
  template — same known, declined gap as SONiC's D6, not a new issue). The Important finding — a routed-SVI
  stanza dereferencing `segment.vrf.node.name.value` without guarding `segment.vrf.node` itself — was **fixed
  inline**.
- Fix commit: `8f69edf` — "fix(cumulus): guard vrf dereference in routed-SVI stanza" (also documented as
  research.md D11).

### Live-stack closure session (T019-T025, T034-T035)

Docker became available in this environment after the implementation/review passes above. Closed out every
task that had been blocked on it:

- **Repository re-sync gotcha**: the running stack's `CoreRepository` object was pinned to a stale commit;
  neither re-loading `repository.yml` nor the `InfrahubRepositoryProcess` GraphQL mutation forced a re-clone
  at current `HEAD`. Resolved with a full `inv destroy && inv start && inv load`, which forces a clean
  re-clone. Worth noting for whoever next hits this: there is no lighter-weight "force resync" path found in
  this repo's SDK/API surface at this Infrahub version.
- Ran the full generator chain (`generate-fabric`/`generate-pod`/`generate-rack`/`generate-tenant`) for **all
  six fabrics**, not just Fabric-F, to make the cross-vendor checks (T022, T025) meaningful. 140 devices
  generated, matching data-model.md's predicted inventory exactly.
- Triggered all six vendors' `artifact_definitions` via `POST /api/artifact/generate/{id}`; confirmed **140/140
  devices with exactly one artifact**.
- Fetched and inspected **real rendered artifacts** (not mock data) for a Cumulus leaf, a spine from each of
  the three Spectrum generations, and the super-spine — confirming every one of contract rules A1-A8 against
  actual output. Full detail in `tasks.md` T019-T025.
- Live day-two test: created a fourth segment via a `NetworkSegmentCreate` mutation, re-ran `generate-tenant`,
  confirmed the leaf picked it up and a spine/super-spine's artifacts diffed byte-identical before/after (A8),
  then deleted the test segment and re-generated to restore standard `inv load` output.
- Sanity-checked a Cisco and a SONiC device's artifacts on the same post-Cumulus-load stack — both still
  render correctly in their native syntax.
- `tests/integration` was re-run with Docker available: still 25 errors, all in generic
  `infrahub_testcontainers` setup steps (`test_load_schema`/`test_create_groups`/`test_load_repository`)
  affecting every vendor's integration suite equally, not something this feature's changes touch — unchanged
  from the pre-Cumulus baseline, so treated as a pre-existing environment/test-infra gap, not a regression.
- Commit: `df57b4b` — "test(cumulus): close out T019-T025, T034-T035 against a live stack"

---

## 2. Tasks not completed

| Task | Reason |
|---|---|
| T036 | Not started — requires a human reviewer with production Cumulus Linux/FRR experience; no such reviewer was available during this run. This is the SC-001 acceptance gate — the only remaining open item in the feature. |

Recorded in `tasks.md` with an explicit not-started annotation, not silently left as a bare `[ ]` checkbox.

---

## 3. Local-pass evidence

| Test id | Type | Run command | Passed at (ISO 8601) | Environment context | Verbatim pass line |
|---|---|---|---|---|---|
| `tests/unit/test_vendors.py` (all, incl. new `Cumulus-cumulus_devices` case) | unit | `uv run pytest tests/unit/test_vendors.py tests/unit/test_cumulus_device_templates.py -v` | 2026-09-02T13:48:57Z (Chunk 1) | n/a (pure Python, no fixtures) | `61 passed in 0.58s` |
| `tests/unit/test_cumulus_device_templates.py` (all, new file) | unit | `uv run pytest tests/unit/test_vendors.py tests/unit/test_cumulus_device_templates.py -v` | 2026-09-02T13:48:57Z (Chunk 1) | n/a | `61 passed in 0.58s` |
| Full unit suite (regression check) | unit | `uv run pytest tests/unit -q` | 2026-09-02 (Chunk 1, re-confirmed by orchestrator after Chunk 4 fix) | n/a | `311 passed in 1.29s` |

`startup_config_cumulus.j2` itself has no automated test (repo-wide precedent, research.md D6) — but it has
now been exercised three separate times: Chunk 2's synthetic-render verification, the Phase 6 code-review
agent's independent re-rendering, and the live-stack closure session's real generated artifacts (140 devices,
inspected against every contract acceptance rule). None of these is a repeatable CI-enforced test — consistent
with how SONiC's own template is (and remains) unverified by automation — but the live-stack pass is the
strongest evidence available short of adding one.

No `MISSING` rows. No E2E tests exist in this repo for this feature class. `tests/integration` was run with
Docker available in the live-stack closure session; its 25 errors are generic environment-setup failures
(`infrahub_testcontainers`) affecting every vendor equally, unrelated to this feature's code, and unchanged
from the pre-Cumulus baseline — not a Cumulus-specific test gap.

---

## 4. Review findings

| Severity | Agent | File | Summary | Outcome |
|---|---|---|---|---|
| Important | errors | `transforms/templates/startup_config_cumulus.j2:145` | Routed-SVI stanza guarded on `segment.gateway.node` but dereferenced `segment.vrf.node.name.value` unguarded — a null `vrf` relationship would abort the whole artifact render | **Fixed inline** (commit `8f69edf`) |
| Suggestion | comments | `docs/docs/solution-ai-dc/evpn-vxlan-overlay.mdx` | Could name "ifupdown2" explicitly for parity with the template's own banner comment | Deferred (cosmetic, not inaccurate) |
| Suggestion | errors | `transforms/templates/startup_config_cumulus.j2` | No automated Jinja2 render test exists | Deferred — this is research.md D6's repo-wide, deliberate precedent (shared by all six vendors), not a Cumulus-specific gap |

`code` and `tests` review passes returned zero findings of any severity.

---

## 5. Autonomous decisions

- **Committed directly to `main`, no feature branch.** The prep phase (specify/plan/critique/tasks) had
  already committed to `main` before this implementation phase started (no `006-cumulus-vendor-support` branch
  exists in the repo), so every implementation chunk continued on `main` rather than creating a branch
  retroactively.
- **Chunked as: Foundational → Template+Data → Docs, with validation/closing handled by the orchestrator
  directly** rather than as its own subagent dispatch, since most of Phase 3's Validation and Phase 4's
  closing tasks (T019-T025, T033-T036) reduce to "run this against a live stack" or "needs a human" — dispatching
  a subagent for tasks that cannot make progress in this sandbox would have wasted a dispatch. T018 and T033
  (the two verifiable-without-Docker items) were confirmed directly instead.
- **`docker info` was checked twice** (once before dispatching Chunk 1, once after Chunk 3) to confirm the
  Docker-unavailability constraint wasn't transient; it was not.
- **The Important review finding was fixed only in `startup_config_cumulus.j2`, not in
  `startup_config_sonic.j2`** where the identical unguarded chain also exists — touching SONiC's template is
  explicitly Out of Scope for this feature (spec Out of Scope: "Changes to the Cisco, Arista, Dell, Juniper or
  SONiC templates to any new standard"; FR-010 forbids altering existing vendors' rendered output). Recorded
  as research.md D11 so it isn't lost as a future finding for whoever next touches SONiC's template.
- **`types` and `simplify` review passes were skipped** — no new type design exists in this feature to review,
  and the four passes that did run returned essentially clean, giving no simplification target to chase.

---

## 6. Suggested next steps

1. **Line up a reviewer with production Cumulus Linux/FRR experience for the SC-001 gate (T036)** — this is
   the only remaining open item. Brief them with the scoped mandate in `quickstart.md`'s Review gate section,
   and specifically ask them to confirm the two mechanics flagged as hedged-but-unverified in
   `critiques/critique-20260902-154300.md` (E1: the `link-down yes`/omit-`auto` admin-down convention; E2: the
   deliberate STP-guard omission) — both are also visible directly in the real leaf/spine artifacts captured
   during the live-stack session.
2. Once T036 completes with zero blocking findings, the feature is ready to consider done.
3. **Optional**: apply the cosmetic docs Suggestion (naming "ifupdown2" explicitly in
   `evpn-vxlan-overlay.mdx`) — low priority, not blocking.
4. Run `/speckit.opsmill.extract` (manual follow-up, per the auto-pipeline's design) once T036 closes, to fold
   this feature's decisions into the project's permanent documentation/ADRs.
5. Consider whether the "`InfrahubRepositoryProcess` mutation doesn't force a re-clone at HEAD" gotcha found
   during closure is worth a note in `dev/guides/` for future vendor additions in this repo — it cost real
   time to diagnose and a full `inv destroy`/`inv start` was the only reliable fix found.

---

STATUS: DONE | SPEC_DIR: /Users/Xavier/Documents/Code/infrahub-solution-ai-dc/specs/006-cumulus-vendor-support | REASON: 35/36 tasks done with full live-stack verification; only T036 (human Cumulus/FRR reviewer for the SC-001 acceptance gate) remains, which by design cannot be performed by an agent
