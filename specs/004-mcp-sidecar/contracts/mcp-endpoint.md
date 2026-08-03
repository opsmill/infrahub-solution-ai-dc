# Contract: MCP endpoint exposed by the sidecar

This feature adds no new interface of its own. It publishes an **existing** upstream
interface — the Infrahub MCP server's HTTP surface — at a known address on the developer's
machine. This file records the part of that surface this repository depends on, so a future
image bump can be checked against it.

Upstream owner: `opsmill/infrahub-mcp`. This repository consumes; it does not define.

## Endpoints consumed

| Path | Method | Consumed by | Purpose |
|------|--------|-------------|---------|
| `/mcp` | POST | MCP clients (Claude Code and others) | MCP Streamable HTTP transport |
| `/health` | GET | The compose health check, and the quickstart walkthrough | Readiness probe |

`/metrics` exists upstream but is not used here.

Base address on the host: `http://localhost:${INFRAHUB_MCP_PORT:-8001}`.
Inside the compose network the container listens on `0.0.0.0:8001`.

## Authentication contract

Mode: `token-passthrough`.

- Every request to `/mcp` must carry `Authorization: Bearer <infrahub-api-token>`.
- The server extracts that token and builds a per-request Infrahub client with it. There are
  no server-side credentials, so what the caller may do is exactly what the token's Infrahub
  account may do (FR-006).
- **Fail-closed**: a missing or empty header is rejected. There is no fallback to shared
  credentials. A token that is valid syntax but wrong for this instance fails the same way.
- `/health` needs no token. In passthrough mode it verifies that the Infrahub address is
  configured, not that any credential works.

## Behaviour this repository relies on

| Expectation | Why it matters here |
|-------------|---------------------|
| Server listens with the Streamable HTTP transport by default in the image | No `command:` override in the compose service |
| Bind address and port default to `0.0.0.0:8001` | The published port maps straight to 8001 |
| Session branches are created with `sync_with_git=False` | Agent sessions never create git branches (spec Story 2, scenario 2) |
| `INFRAHUB_MCP_BRANCH_PATTERN` accepts `{date}` and `{hex}` placeholders | The pinned `mcp/session-{date}-{hex}` naming (FR-009) |
| Tool names are stable | The vendored skills call `mcp__infrahub__*` (FR-008) |
| Passthrough mode requires the HTTP transport, not stdio | Why this must be a sidecar rather than a local process |

## Verifying the contract after an image bump

```bash
# health
curl -s http://localhost:${INFRAHUB_MCP_PORT:-8001}/health

# fail-closed: no Authorization header -> rejected
curl -s -o /dev/null -w '%{http_code}\n' -X POST http://localhost:${INFRAHUB_MCP_PORT:-8001}/mcp \
  -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'

# with a token -> tools listed, including the mcp__infrahub__* set the skills call
curl -s -X POST http://localhost:${INFRAHUB_MCP_PORT:-8001}/mcp \
  -H "Authorization: Bearer ${INFRAHUB_API_TOKEN:-06438eb2-8019-4776-878c-0941b1f1d1ec}" \
  -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

If a bump changes any row in the table above, the compose service or `.mcp.json` needs
updating with it — that is the whole reason the version is pinned (FR-004).
