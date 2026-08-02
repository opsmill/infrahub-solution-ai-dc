---

description: "Task list for the Infrahub MCP sidecar feature"
---

# Tasks: Infrahub MCP server as an always-on sidecar

**Input**: Design documents from `/specs/004-mcp-sidecar/`

**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md),
[data-model.md](./data-model.md), [contracts/mcp-endpoint.md](./contracts/mcp-endpoint.md),
[quickstart.md](./quickstart.md) — all complete and post-critique.

**Tests**: One test task is included — `tests/unit/test_mcp_config.py`, added on the
critique's E5 recommendation because FR-001, FR-002 and FR-008 are file-shape invariants a
future edit could silently break. No other tests: this feature adds no code paths to cover.

**Organization**: Both user stories are served by the *same* two artefacts — the compose
service and the client config. Rather than invent per-story implementation tasks, Phase 2
builds the shared capability that both stories need, Phase 3 covers the shared
documentation, and the story phases (4 and 5) contain each story's acceptance walkthrough.
That is where the stories actually diverge, and each remains independently verifiable.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1, US2)
- **[MANUAL]**: Needs Docker, image pulls, and/or an interactive agent session — a headless
  run cannot complete these and must report them as pending rather than claim them done

## Path Conventions

Repository root paths. No `src/` changes in this feature; the only Python addition is under
`tests/unit/`.

---

## Phase 1: Setup

**Purpose**: Confirm the pinned dependency is actually available before writing config against it

- [X] T001 Confirm the pinned image tag resolves anonymously: `docker manifest inspect registry.opsmill.io/opsmill/infrahub-mcp:v1.1.7`. If it fails, stop and re-pin using the tag list procedure in [research.md](./research.md) — do not fall back to `latest` (FR-004)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The sidecar and the client config. Both user stories depend on these

**⚠️ CRITICAL**: No story acceptance work can begin until T005 passes

- [X] T002 [P] Add the `infrahub-mcp` service to `docker-compose.override.yml` exactly as specified in [plan.md](./plan.md) "Implementation shape §1": pinned image via `${INFRAHUB_MCP_VERSION:-v1.1.7}`, literal `INFRAHUB_ADDRESS: "http://infrahub-server:8000"`, `INFRAHUB_MCP_AUTH_MODE: token-passthrough`, `INFRAHUB_MCP_BRANCH_PATTERN: "mcp/session-{date}-{hex}"`, `INFRAHUB_MCP_LOG_LEVEL` and `INFRAHUB_MCP_READ_ONLY` with defaults, `ports: - ${INFRAHUB_MCP_PORT:-8001}:8001`, `depends_on: infrahub-server: condition: service_healthy`, `restart: unless-stopped`, and the `python urllib` healthcheck. No `profiles:`, no `command:`, and no credential key of any kind (FR-001, FR-004, FR-007, FR-009, FR-010). Keep lines within the 140-character yamllint limit
- [X] T003 [P] Create `.mcp.json` at the repository root per [plan.md](./plan.md) "Implementation shape §2": strict JSON, single server keyed `infrahub`, `"type": "http"`, `"url": "http://localhost:${INFRAHUB_MCP_PORT:-8001}/mcp"`, and `Authorization: Bearer ${INFRAHUB_API_TOKEN:-06438eb2-8019-4776-878c-0941b1f1d1ec}`. No comments (FR-002, FR-005, FR-007, FR-008)
- [X] T004 Create `tests/unit/test_mcp_config.py` guarding the three invariants listed in [plan.md](./plan.md) "Implementation shape §4": `.mcp.json` parses and registers `infrahub` with `type: http`; the auth header references `${INFRAHUB_API_TOKEN`; the `infrahub-mcp` service block carries no `token`/`password`/`username` key. Read the files from the repository root — no Docker, no network. Annotate functions `-> None` for mypy strict mode (depends on T002, T003)
- [ ] T005 Local validation gate — all four must pass: `docker compose config >/dev/null`, `python -m json.tool .mcp.json >/dev/null`, `uv run inv lint`, `uv run inv test` (depends on T002, T003, T004)

**Checkpoint**: The sidecar is defined, the client config exists, and the repository's own gates pass. Story acceptance can begin

---

## Phase 3: Documentation (Cross-Cutting)

**Purpose**: The three documentation touch points. Disjoint files, so all three run in parallel

- [ ] T006 [P] Add a `## AI agent access (MCP server)` section to `README.md` after **Quick start**: the sidecar starts with `inv start`, `.mcp.json` is already wired, approve the `infrahub` server at the one-time prompt on first run, `export INFRAHUB_API_TOKEN=<token>` to use your own token, `INFRAHUB_MCP_PORT` if 8001 is taken. Informational only — never phrased as a prerequisite (FR-003, SC-001)
- [ ] T007 [P] Update `docs/docs/solution-ai-dc/installation-setup.mdx`: (a) add `INFRAHUB_API_TOKEN` to **Configure environment variables** beside the existing `INFRAHUB_USERNAME` / `INFRAHUB_PASSWORD` exports; (b) add an `### Infrahub MCP server` subsection after **Start Infrahub** covering what the sidecar is, `curl http://localhost:8001/health`, the one-time approval, pinning and bumping `INFRAHUB_MCP_VERSION`, one factual sentence that the endpoint is published on all interfaces like Infrahub's own port, a non-Claude client snippet (`streamable-http` plus `Authorization: Bearer`), and that agent writes land on `mcp/session-*` branches reviewed through a proposed change; (c) add three **Troubleshooting** entries — authentication failures (check `echo $INFRAHUB_API_TOKEN`), port already in use (`export INFRAHUB_MCP_PORT=…`), and image pull failure (`INFRAHUB_MCP_VERSION` / `INFRAHUB_MCP_DOCKER_IMAGE`)
- [ ] T008 [P] Add one line to the **Agentic Layout** section of `AGENTS.md` naming `.mcp.json` and the `infrahub-mcp` sidecar as how agents reach live Infrahub data
- [ ] T009 Review the three edited files against FR-003: the token override appears as a mechanical `export`, there is no caveat, warning, or commentary about the committed demo credential anywhere, the word "overlay" is never used for the compose override file, and the one-time approval is mentioned in both user-facing documents (depends on T006, T007, T008)

**Checkpoint**: A reader can find the feature and use it without reading the spec

---

## Phase 4: User Story 1 - Ask live Infrahub questions through an agent (Priority: P1) 🎯 MVP

**Goal**: Read-only agent access to live demo data after the documented start-up commands

**Independent Test**: Bring the stack up, approve the server once, ask a question only
Infrahub can answer — no dependency on Story 2

- [ ] T010 [MANUAL] [US1] Run `uv run inv start`, wait for `docker compose ps infrahub-mcp` to report `healthy`, and confirm `curl -s http://localhost:8001/health` responds. Confirms FR-010 — plain `inv start`, no flag, no profile, no `tasks.py` change
- [ ] T011 [MANUAL] [US1] Run the fail-closed pair from [contracts/mcp-endpoint.md](./contracts/mcp-endpoint.md): `POST /mcp` with no `Authorization` header is rejected; the same call with `Bearer 06438eb2-8019-4776-878c-0941b1f1d1ec` returns a tool list
- [ ] T012 [MANUAL] [US1] Before running `inv load`: with `INFRAHUB_API_TOKEN` unset, run `claude mcp list` (expect `⏸ Pending approval`, and **no** missing-variable warning), approve `infrahub` in an interactive session, then ask the demo-fabric question — expect a successful empty result, not an authentication or connection error (spec Story 1 scenario 2)
- [ ] T013 [MANUAL] [US1] Run `uv run inv load`, then ask the same question again — expect a real answer sourced from `mcp__infrahub__*` tool calls, with no local server process started and no credential typed (spec Story 1 scenario 1; SC-001, SC-004, FR-002, FR-005, FR-008)

**Checkpoint**: Story 1 is complete and demonstrable on its own — this is the MVP

---

## Phase 5: User Story 2 - Create data and open a proposed change through an agent (Priority: P2)

**Goal**: Agent writes land on an identifiable session branch and reach a human as a proposed change

**Independent Test**: Ask for one object plus a proposed change; confirm the branch, the
proposed change, and that nothing merged

- [ ] T014 [MANUAL] [US2] Ask the agent to create one object and open a proposed change. Verify in the Infrahub UI: a branch named `mcp/session-<date>-<hex>` exists (FR-009), the change is recorded on it, and a `CoreProposedChange` targeting `main` is open and unmerged (FR-006)
- [ ] T015 [MANUAL] [US2] Confirm `git branch -a` shows no new git branch — the session branch is data-only (spec Story 2 scenario 2, matching the `sync_with_git=False` finding in [research.md](./research.md))

**Checkpoint**: Both stories work independently

---

## Phase 6: Polish & Cross-Cutting Concerns

- [ ] T016 [MANUAL] Port override: `uv run inv stop`, then `INFRAHUB_MCP_PORT=8011 uv run inv start`, confirm the container publishes 8011 and `INFRAHUB_MCP_PORT=8011 claude mcp list` still connects — one variable, both sides, no file edited (FR-007)
- [ ] T017 [MANUAL] Teardown: `uv run inv stop`, then confirm `docker compose ps -a` leaves no `infrahub-mcp` container
- [ ] T018 [MANUAL] Walk [quickstart.md](./quickstart.md) end to end and record the outcome of each numbered step as the feature's acceptance evidence
- [ ] T019 Commit with explicit paths only — `docker-compose.override.yml`, `.mcp.json`, `tests/unit/test_mcp_config.py`, `README.md`, `docs/docs/solution-ai-dc/installation-setup.mdx`, `AGENTS.md`, and the `specs/004-mcp-sidecar/` artefacts. Never `git add .`: the working tree carries unrelated in-flight work (modified `Dockerfile`, untracked `rules.yml`, `specs/003-juniper-junos-support/`, `transforms/templates/startup_config_juniper.j2`) that must stay uncommitted

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Setup)**: no dependencies
- **Phase 2 (Foundational)**: needs T001 — blocks all story work
- **Phase 3 (Documentation)**: needs nothing from Phase 2 in principle, but describes what
  Phase 2 builds, so write it after T002 and T003 land to keep the prose truthful
- **Phase 4 (US1)**: needs T005
- **Phase 5 (US2)**: needs T005; independent of Phase 4, though in practice the same running
  stack and the same one-time approval serve both
- **Phase 6 (Polish)**: needs the story phases whose evidence it records

### Task-Level Dependencies

```text
T001 → T002 ─┐
         T003 ─┼→ T004 → T005 → T010 → T011 → T012 → T013   (US1)
              │                    └────────────→ T014 → T015   (US2)
              └→ T006, T007, T008 → T009
                                              T016, T017, T018 → T019
```

### Parallel Opportunities

- T002 and T003 touch disjoint files and can run together
- T006, T007 and T008 touch three disjoint files and can run together
- Phase 4 and Phase 5 acceptance can share one running stack

---

## Parallel Example

```bash
# Foundational artefacts — disjoint files
Task: "Add the infrahub-mcp service to docker-compose.override.yml"
Task: "Create .mcp.json at the repository root"

# Documentation — three disjoint files
Task: "Add the AI agent access section to README.md"
Task: "Update docs/docs/solution-ai-dc/installation-setup.mdx"
Task: "Add the Agentic Layout line to AGENTS.md"
```

---

## Implementation Strategy

### MVP scope

Phases 1–4. That delivers Story 1: the sidecar, the client config, the automated guard, the
documentation, and a verified read path. Story 2 needs no further implementation — the same
server serves it — so Phase 5 is acceptance only.

### What a headless run can and cannot finish

Automatable without a human: **T001–T009 and T019** — every file change plus
`docker compose config`, `python -m json.tool`, `inv lint`, and `inv test`.

Not automatable: **T010–T018**, marked `[MANUAL]`. They need a running stack, image pulls
from the registry, and an interactive agent session in which a human accepts the one-time
project-scoped server approval — which, per [spec.md](./spec.md) Assumptions, a cloned
repository cannot grant itself. A headless run must report these as pending with that
reason, not mark them complete.
