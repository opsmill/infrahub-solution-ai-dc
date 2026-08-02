# Implementation Plan: Infrahub MCP server as an always-on sidecar

**Branch**: `wvd/chore-mcp-sidecar-passthrough` | **Date**: 2026-08-02 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/004-mcp-sidecar/spec.md`

## Summary

Add an `infrahub-mcp` service to the compose override file so the Infrahub MCP server runs
from a pinned image alongside the rest of the stack, and commit a `.mcp.json` that points
clients at it. The server runs in `token-passthrough` mode, so it is configured with no
Infrahub credential and each client presents its own token in the `Authorization` header.
Documentation gains an informational section in three places. No Python changes: `inv start`
already runs `docker compose up -d`, which picks the new service up.

## Technical Context

**Language/Version**: YAML (Docker Compose v2 schema) and strict JSON. No application code.

**Primary Dependencies**: `registry.opsmill.io/opsmill/infrahub-mcp:v1.1.7` (new external
image); the existing Infrahub 1.10.0 stack from the downloaded `docker-compose.yml`.

**Storage**: N/A — the sidecar is stateless; agent writes land in Infrahub's graph.

**Testing**: `uv run inv lint` (yamllint covers the override file) plus the manual
end-to-end walkthrough in [quickstart.md](./quickstart.md). No unit-testable code is added,
so no pytest changes.

**Target Platform**: Docker Compose on a developer machine (Linux or macOS).

**Project Type**: Infrastructure and developer-experience configuration for an existing
reference-implementation repository.

**Performance Goals**: None. Tool latency belongs to the model and graph size, not to this
change.

**Constraints**:

- yamllint line length 140 (`.yamllint.yml` via `inv lint`).
- `.mcp.json` is strict JSON — no comments are possible, and none are wanted.
- The service must carry no Infrahub credential of any kind (FR-001).
- `${VERSION}` must not be reused for the image tag: `.envrc` sets it to `local` for the
  custom Infrahub build, which would resolve to a nonexistent `infrahub-mcp:local`.
- `docker-compose.yml` is downloaded by `tasks.py` and must not be hand-edited; every
  repository-owned addition goes in the compose override file.

**Scale/Scope**: One new compose service, one new root config file, three documentation
touch points. Single-user disposable demo stack.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

`.specify/memory/constitution.md` is the unmodified spec-kit template — it contains
placeholder principles (`[PRINCIPLE_1_NAME]`) and no ratified content, and there is no
`dev/constitution.md` either. There are therefore **no project principles to gate against**.
This is recorded as "not applicable", not as "passed": no principle was evaluated.

The repository's actual written rules that this feature could violate live in `AGENTS.md`
and were checked directly instead:

| Rule | Status |
|------|--------|
| Query response models (`*_query.py`) are generated — do not edit manually | Not touched |
| Vendored `infrahub-*` skills are pinned by `skills-lock.json` | Not touched |
| `CONTEXT.md` reserves "Overlay" for the EVPN control plane | Prose says "compose override file" |
| Code style (ruff/mypy, line lengths) | No Python changes; yamllint 140 respected |

**Post-Phase 1 re-check**: unchanged — the design adds no Python, no schema, and no
generated artefacts.

## Project Structure

### Documentation (this feature)

```text
specs/004-mcp-sidecar/
├── plan.md              # This file
├── research.md          # Phase 0 output — verified facts behind the fixed decisions
├── data-model.md        # Phase 1 output — configuration entities (no Infrahub schema change)
├── quickstart.md        # Phase 1 output — end-to-end verification walkthrough
├── contracts/
│   └── mcp-endpoint.md  # Phase 1 output — the observable HTTP contract clients rely on
├── checklists/
│   └── requirements.md  # Spec quality checklist
└── tasks.md             # Phase 2 output (/speckit-tasks)
```

### Source Code (repository root)

```text
docker-compose.override.yml   # MODIFIED — new `infrahub-mcp` service
.mcp.json                     # NEW — committed client configuration
README.md                     # MODIFIED — informational section after Quick start
AGENTS.md                     # MODIFIED — one line in Agentic Layout
docs/docs/solution-ai-dc/
└── installation-setup.mdx    # MODIFIED — env var, MCP subsection, troubleshooting
tests/unit/
└── test_mcp_config.py        # NEW — guards FR-001, FR-002, FR-008 as file-shape invariants
```

**Structure Decision**: No source tree changes. `docker-compose.yml` stays untouched
because `tasks.py::download_compose_file` fetches it from `infrahub.opsmill.io`; the
repository's own service definitions already live in `docker-compose.override.yml`
alongside the custom-build anchor and the `database` / `task-manager` / `task-worker`
overrides. `tasks.py` is deliberately unmodified — `inv start` runs `docker compose up -d`,
which starts the new service with no flag, profile, or new task (FR-010).

## Implementation shape

### 1. `docker-compose.override.yml`

Append one service under the existing `services:` mapping:

```yaml
  infrahub-mcp:
    image: "${INFRAHUB_MCP_DOCKER_IMAGE:-registry.opsmill.io/opsmill/infrahub-mcp}:${INFRAHUB_MCP_VERSION:-v1.1.7}"
    restart: unless-stopped
    depends_on:
      infrahub-server:
        condition: service_healthy
    environment:
      INFRAHUB_ADDRESS: "http://infrahub-server:8000"
      INFRAHUB_MCP_AUTH_MODE: token-passthrough
      INFRAHUB_MCP_BRANCH_PATTERN: "mcp/session-{date}-{hex}"
      INFRAHUB_MCP_LOG_LEVEL: ${INFRAHUB_MCP_LOG_LEVEL:-info}
      INFRAHUB_MCP_READ_ONLY: ${INFRAHUB_MCP_READ_ONLY:-false}
    ports:
      - ${INFRAHUB_MCP_PORT:-8001}:8001
    healthcheck:
      test: ["CMD-SHELL", "python -c \"import urllib.request; urllib.request.urlopen('http://localhost:8001/health')\""]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 5s
```

Traceability: FR-001 (no credential keys present), FR-004 (`INFRAHUB_MCP_VERSION` pin),
FR-007 (`INFRAHUB_MCP_PORT`), FR-009 (`INFRAHUB_MCP_BRANCH_PATTERN`), FR-010 (plain
service, no `profiles:`). No `command:` — the image's own `CMD` runs the server with
`--transport streamable-http` on `0.0.0.0:8001`.

`INFRAHUB_ADDRESS` is deliberately a literal here, not the `${INFRAHUB_ADDRESS:-…}` form the
base compose file uses for `task-worker`. `installation-setup.mdx` teaches users to export
shell variables, and an exported `INFRAHUB_ADDRESS=http://localhost:8000` would resolve
inside this container to the container itself, breaking the sidecar for exactly the user the
feature targets. Keep it literal; the deviation is the point.

### 2. `.mcp.json` (new, repository root)

```json
{
  "mcpServers": {
    "infrahub": {
      "type": "http",
      "url": "http://localhost:${INFRAHUB_MCP_PORT:-8001}/mcp",
      "headers": {
        "Authorization": "Bearer ${INFRAHUB_API_TOKEN:-06438eb2-8019-4776-878c-0941b1f1d1ec}"
      }
    }
  }
}
```

Traceability: FR-002 (token from the environment), FR-005 (fallback makes a fresh clone
work with no manual step), FR-007 (same port variable as the service), FR-008 (server key
`infrahub`).

### 3. Documentation

| File | Change |
|------|--------|
| `README.md` | New `## AI agent access (MCP server)` section after **Quick start**: the sidecar starts with `inv start`, `.mcp.json` is already wired, approve the `infrahub` server at the one-time prompt on first run, `export INFRAHUB_API_TOKEN=<token>` to use your own, `INFRAHUB_MCP_PORT` if the port is taken. Informational — never a prerequisite (SC-001). |
| `docs/docs/solution-ai-dc/installation-setup.mdx` | (a) add `INFRAHUB_API_TOKEN` to **Configure environment variables** (~line 39); (b) new `### Infrahub MCP server` subsection after **Start Infrahub** — what the sidecar is, `curl http://localhost:8001/health`, the one-time approval on first run, pinning/bumping `INFRAHUB_MCP_VERSION`, one factual sentence that the endpoint is published on all interfaces like Infrahub's own port, a non-Claude client snippet, and that agent writes land on `mcp/session-*` branches reviewed through a proposed change; (c) three **Troubleshooting** entries — tool calls failing authentication (check `echo $INFRAHUB_API_TOKEN`), the port already in use (`export INFRAHUB_MCP_PORT=…`), and an image pull failure (`INFRAHUB_MCP_VERSION` / `INFRAHUB_MCP_DOCKER_IMAGE`). |
| `AGENTS.md` | One line in **Agentic Layout**: `.mcp.json` plus the `infrahub-mcp` sidecar as how agents reach live Infrahub data. |

Write mechanically (FR-003): show `export INFRAHUB_API_TOKEN=<token>` and stop. No caveat,
warning, or commentary about the committed demo credential anywhere. Never write "overlay"
for the compose override file.

### 4. `tests/unit/test_mcp_config.py` (new)

Three requirements are file-shape invariants that a future edit could silently break, so
they get an automated guard in the existing suite (`pytest tests` via `inv test`):

- `.mcp.json` parses as strict JSON, registers exactly the server key `infrahub`, and that
  entry has `type: http` (FR-008).
- The `Authorization` header references `${INFRAHUB_API_TOKEN`, so the token comes from the
  environment rather than a pasted literal (FR-002).
- The `infrahub-mcp` service block in `docker-compose.override.yml` declares no **key**
  matching `token`, `password`, or `username` (FR-001). Keys only, deliberately: the service
  legitimately carries `INFRAHUB_MCP_AUTH_MODE: token-passthrough`, whose *value* contains
  "token". Scanning values would flag the very setting that removes the credentials.

Read the two files as text/YAML from the repository root — no Docker, no network, no running
stack, so it stays in the fast unit suite. mypy runs in strict mode, so annotate the test
functions (`-> None`).

### 5. Not modified

`tasks.py`, `docker-compose.yml` (downloaded), `CONTEXT.md`, and the vendored
`.agents/skills/infrahub-*` skills.

## Complexity Tracking

No constitution violations to justify (no ratified constitution). The design adds one
container and one config file, which is the minimum that satisfies FR-005 and FR-010.
