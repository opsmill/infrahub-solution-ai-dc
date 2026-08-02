# Phase 1 Data Model: Infrahub MCP server as an always-on sidecar

**No Infrahub schema change.** Nothing in `schemas/` is touched, no node kind is added or
altered, and no object file changes. The entities below are configuration and runtime
entities, recorded so `tasks.md` and the review phase have named things to check.

## Configuration entities

### MCP sidecar service

The `infrahub-mcp` service in `docker-compose.override.yml`.

| Field | Value | Requirement |
|-------|-------|-------------|
| `image` | `${INFRAHUB_MCP_DOCKER_IMAGE:-registry.opsmill.io/opsmill/infrahub-mcp}:${INFRAHUB_MCP_VERSION:-v1.1.7}` | FR-004 |
| `INFRAHUB_ADDRESS` | `http://infrahub-server:8000` (internal container network) | — |
| `INFRAHUB_MCP_AUTH_MODE` | `token-passthrough` | FR-001, FR-006 |
| `INFRAHUB_MCP_BRANCH_PATTERN` | `mcp/session-{date}-{hex}` | FR-009 |
| `INFRAHUB_MCP_LOG_LEVEL` | `${INFRAHUB_MCP_LOG_LEVEL:-info}` | — |
| `INFRAHUB_MCP_READ_ONLY` | `${INFRAHUB_MCP_READ_ONLY:-false}` | — |
| `ports` | `${INFRAHUB_MCP_PORT:-8001}:8001` | FR-007 |
| `depends_on` | `infrahub-server` → `service_healthy` | Edge case: Infrahub still starting |
| `restart` | `unless-stopped` | — |
| `healthcheck` | `python urllib` against `http://localhost:8001/health` | — |
| `profiles` | **absent** | FR-010 |
| credential keys | **none** — no API token, username, or password | FR-001 |

**Validation rules**:

- No key whose name or value carries an Infrahub credential may appear in this service.
- The image tag must never be `latest` or `${VERSION}`.
- Lines must stay within the 140-character yamllint limit.

### Committed client configuration

`.mcp.json` at the repository root. One server entry.

| Field | Value | Requirement |
|-------|-------|-------------|
| server key | `infrahub` | FR-008 |
| `type` | `http` | Required — a `url` with no `type` is a configuration error |
| `url` | `http://localhost:${INFRAHUB_MCP_PORT:-8001}/mcp` | FR-007 |
| `headers.Authorization` | `Bearer ${INFRAHUB_API_TOKEN:-06438eb2-8019-4776-878c-0941b1f1d1ec}` | FR-002, FR-005 |

**Validation rules**:

- Strict JSON — parseable by `python -m json.tool`, no comments.
- The token must be an environment-variable reference; the only permitted inline value is
  the public demo token already present at `docker-compose.yml:303`.
- The port variable must be the same one the service publishes.

### Environment variables (the user-facing contract)

| Variable | Default | Effect |
|----------|---------|--------|
| `INFRAHUB_API_TOKEN` | demo admin token | Credential the client presents; sets what the agent may do |
| `INFRAHUB_MCP_PORT` | `8001` | Published host port **and** the client's address |
| `INFRAHUB_MCP_VERSION` | `v1.1.7` | Server image tag |
| `INFRAHUB_MCP_DOCKER_IMAGE` | Opsmill registry path | Image repository |
| `INFRAHUB_MCP_LOG_LEVEL` | `info` | Server log verbosity |
| `INFRAHUB_MCP_READ_ONLY` | `false` | Hides and rejects write tools when `true` |

Documented in `installation-setup.mdx`; the first three also appear in `README.md`.

## Runtime entity

### Session branch

Created in Infrahub by the server when an agent first writes.

- **Name**: `mcp/session-<date>-<hex>`, from the pinned pattern.
- **Kind**: Infrahub branch, `sync_with_git=False` — data-only, creates no git branch.
- **Lifecycle**: created on first write in a session; reviewed through a
  `CoreProposedChange` targeting the default branch; never auto-merged; removed with the
  stack on `inv destroy`.
- **Permissions**: whatever the presented `INFRAHUB_API_TOKEN` grants (FR-006).

## State transitions (Story 2)

```text
no session branch
   → agent write        → mcp/session-<date>-<hex> created, change recorded on it
   → propose_changes    → CoreProposedChange (branch → default) open for human review
   → human merges       → change lands on the default branch
   → inv destroy        → branch and proposed change gone with the stack
```

Nothing in this feature performs the merge step.
