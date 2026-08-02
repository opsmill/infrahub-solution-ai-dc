# Quickstart: verifying the Infrahub MCP sidecar

End-to-end validation for `specs/004-mcp-sidecar`. Run it after implementation; every step
names what proves which requirement.

## Prerequisites

- Docker and Docker Compose v2
- `uv sync --all-packages` already run
- Anonymous pull access to `registry.opsmill.io` (no login needed)
- For the Story 1 and Story 2 steps: Claude Code, launched from the repository root

## 1. Configuration is valid

```bash
docker compose config >/dev/null && echo "compose OK"
python -m json.tool .mcp.json >/dev/null && echo "json OK"
uv run inv lint
```

Expected: all three succeed. `docker compose config` resolving proves the override file
merges with the downloaded `docker-compose.yml`; `inv lint` runs yamllint over it.

## 2. No credentials in the service

```bash
docker compose config | sed -n '/infrahub-mcp/,/^  [a-z]/p' | grep -iE 'token|password|username'
```

Expected: **no output** — proves FR-001 against the *resolved* config, not just the file.

```bash
docker compose config | grep -A2 'infrahub-mcp' | grep 'image:'
```

Expected: an explicit `v1.1.7` tag, never `latest` (FR-004, SC-003).

## 3. The stack comes up with the sidecar

```bash
uv run inv start
uv run inv load
docker compose ps infrahub-mcp
```

Expected: `infrahub-mcp` present and `healthy`, started by plain `inv start` with no flag,
profile, or extra task (FR-010). No `tasks.py` change was needed.

```bash
curl -s http://localhost:8001/health
```

Expected: a healthy response.

## 4. Authentication is fail-closed

```bash
# no Authorization header
curl -s -o /dev/null -w '%{http_code}\n' -X POST http://localhost:8001/mcp \
  -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'

# with the demo token
curl -s -X POST http://localhost:8001/mcp \
  -H "Authorization: Bearer 06438eb2-8019-4776-878c-0941b1f1d1ec" \
  -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | head -c 400
```

Expected: the first call is rejected (no success status, no tool list); the second returns
tools. Proves the passthrough contract in
[contracts/mcp-endpoint.md](./contracts/mcp-endpoint.md).

## 5. Story 1 — read path with nothing exported

```bash
unset INFRAHUB_API_TOKEN
claude mcp list
```

Expected: `infrahub` listed and connected, with **no** missing-variable warning — the
`.mcp.json` fallback covers it (FR-002, FR-005).

Then, in a Claude Code session started at the repository root:

1. Run `/mcp` — the `infrahub` server and its tools are listed.
2. Ask a question that can only be answered from Infrahub, e.g. *"how many leaf switches are
   in Fabric-A?"*

Expected: the answer comes from `mcp__infrahub__*` tool calls (FR-008), with no local server
process started and no credential typed. This is SC-001 and SC-004 together — it also proves
container-to-container addressing, since the container reaches Infrahub at
`http://infrahub-server:8000`.

Second scenario from the spec: with the stack up but before `inv load`, the same question
returns empty results rather than an authentication or connection error.

## 6. Story 2 — write path

In a Claude Code session, ask the agent to create one object and open a proposed change.

Expected:

- A branch named `mcp/session-<date>-<hex>` appears in Infrahub (FR-009).
- The change is recorded on that branch, under the presented token's permissions (FR-006).
- A `CoreProposedChange` targeting `main` is visible in the UI, unmerged.
- `git branch -a` shows no new git branch — the session branch is data-only.

## 7. Port override moves both sides at once

```bash
uv run inv stop
INFRAHUB_MCP_PORT=8011 uv run inv start
docker compose ps infrahub-mcp          # published on 8011
INFRAHUB_MCP_PORT=8011 claude mcp list  # infrahub still connected
```

Expected: one variable moved the container and the client together, with no file edited
(FR-007).

## 8. Teardown leaves nothing behind

```bash
uv run inv stop
docker compose ps -a | grep infrahub-mcp
```

Expected: no `infrahub-mcp` container remains. If one lingers, the compose commands in
`tasks.py` need `--profile`-style handling — but with no `profiles:` key on the service,
`docker compose down` removes it with the rest of the project.

## Requirement coverage

| Step | Requirements / criteria |
|------|------------------------|
| 1 | Lint and syntax gates |
| 2 | FR-001, FR-004, SC-002, SC-003 |
| 3 | FR-010 |
| 4 | FR-006 (fail-closed half), endpoint contract |
| 5 | FR-002, FR-005, FR-008, SC-001, SC-004 |
| 6 | FR-006, FR-009 |
| 7 | FR-007 |
| 8 | Clean teardown |

FR-003 (documentation shows the export, mechanically, with no commentary) is verified by
reading the three touched documentation files, not by running anything.
