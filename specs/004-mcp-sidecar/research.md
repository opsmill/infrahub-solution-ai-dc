# Phase 0 Research: Infrahub MCP server as an always-on sidecar

The design decisions arrived fixed in the feature description, so this phase carries no open
`NEEDS CLARIFICATION` items. What it records instead are the facts each decision rests on,
every one of them verified against the two repositories and the registry rather than
assumed. A later reader who wants to change a decision needs these facts, not the argument.

## Published image tags

**Finding**: The image is `registry.opsmill.io/opsmill/infrahub-mcp`. Tags published, newest
first: `latest`, `v1.1.7`, `v1.1.6`, `v1.1.5`, `v1.1.4`, `v1.1.3`, `v1.1.2`, `v1.1.1`
(Harbor artifact listing). Version tags carry a `v` prefix. `pyproject.toml` in the MCP
repository reads `1.1.8`, and the release commit `chore(release): bump to v1.1.8` exists, but
no `v1.1.8` image is in the registry — the tag list and a direct manifest probe both miss.

**Decision**: Pin `v1.1.7`.

**Rationale**: Newest tag that actually resolves. Anonymous pull works, so a fresh clone
needs no registry login.

**Alternatives considered**: `latest` — rejected, it reintroduces the version drift the
feature exists to remove (FR-004). `v1.1.8` — rejected, the image does not exist yet.

## Compatibility with this repository's Infrahub version

**Finding**: The MCP server declares `infrahub-sdk>=1.22.0` and pins Infrahub only through
its dev-group `infrahub-testcontainers>=1.10.0`, so its CI exercises Infrahub 1.10 or newer.
Its `CAPABILITIES.md` marks exactly two tools — shortest-path and reachable-nodes/impact
analysis — as "Requires Infrahub 1.10+". This repository runs 1.10.0.

**Decision**: `v1.1.7` against Infrahub 1.10.0 needs no compatibility shim, and the full
tool set is available.

**Alternatives considered**: Pinning an older MCP version for safety — rejected, it would
lose the two 1.10+ tools for no benefit.

## Session branches and this repository's git-import rule

**Finding**: The MCP server creates its session branch with `sync_with_git=False`
(`src/infrahub_mcp/utils.py:217` and `:246` in the MCP repository, both call sites).

**Decision**: Session branches are data-only and safe to leave at the default naming shape,
pinned explicitly as `mcp/session-{date}-{hex}`.

**Rationale**: Because no git branch is created, agent sessions never interact with this
repository's `INFRAHUB_GIT_IMPORT_SYNC_BRANCH_NAMES: '["^demo/.*$"]'` setting in the compose
override file. Pinning the pattern in the compose file rather than inheriting the image
default (FR-009) keeps the naming discoverable in the repository and means an
`INFRAHUB_MCP_VERSION` bump cannot silently rename agent branches.

**Alternatives considered**: Naming session branches `demo/...` so they sort with the
repository's existing convention — rejected, it would place agent branches inside the
git-import pattern for no gain.

## Client configuration mechanics

**Finding**: Claude Code auto-detects `.mcp.json` at the project root. For HTTP servers the
entry needs `"type": "http"` (`streamable-http` is accepted as an alias); an entry with a
`url` and no `type` is a hard configuration error. Environment expansion — `${VAR}` and
`${VAR:-default}` — is supported in `command`, `args`, `env`, `url`, and `headers`. When a
referenced variable is unset and has no default, the config still loads: the literal
`${VAR}` text is sent and `claude mcp list` shows a missing-variable warning.

**Decision**: `"type": "http"`, with `${INFRAHUB_MCP_PORT:-8001}` in the URL and
`Bearer ${INFRAHUB_API_TOKEN:-<demo token>}` in the headers.

**Rationale**: One variable moving both the published port and the client address (FR-007)
is only possible because expansion works inside the `url` string. The `:-default` on the
token is what makes SC-001 reachable — without it, an unset variable would send a literal
placeholder and every call would fail authentication with a confusing error.

**Alternatives considered**: A token variable with no default — rejected, it breaks
SC-001's "zero MCP-specific steps". A repository-specific variable name such as
`INFRAHUB_MCP_TOKEN` to dodge collisions with a globally exported `INFRAHUB_API_TOKEN`
pointing at a different instance — rejected, `INFRAHUB_API_TOKEN` is the SDK and
`infrahubctl` convention, and such a shell already breaks `infrahubctl` in this repository,
so it is one failure with one fix rather than two names to learn.

## Credential surface

**Finding**: In `token-passthrough` mode the server holds no credentials at all and is
fail-closed: a request with no token is rejected, with no fallback to server-side
credentials. The fallback token in `.mcp.json`, `06438eb2-8019-4776-878c-0941b1f1d1ec`, is
the same public value already committed at `docker-compose.yml:303` as
`INFRAHUB_INITIAL_ADMIN_TOKEN`.

**Decision**: Passthrough mode, container with no credentials, demo token as the inline
client fallback.

**Rationale**: Satisfies FR-001 structurally rather than by convention — there is no
credential key in the service to leak. The inline fallback adds no new exposure: the value
is already in the tree and only grants access to a local disposable stack.

**Alternatives considered**: `basic-passthrough` with the `INFRAHUB_USERNAME` /
`INFRAHUB_PASSWORD` pair the repository already exports — rejected, the header needs a
base64 of `user:pass`, which cannot be assembled from environment variables inside a JSON
config. `none` mode with a shared server-side token — rejected, it puts a credential back
in the compose file.

## Port availability

**Finding**: The running stack publishes 8000 (Infrahub), 4200 (task manager), 7474 and
7687 (database), 2004 and 6362, and 15692. Nothing uses 8001.

**Decision**: Publish `${INFRAHUB_MCP_PORT:-8001}:8001`, on all interfaces like 8000.

**Rationale**: 8001 is free and is the MCP server's own default, so it matches its upstream
documentation. Because 8001 is also a popular default, the variable is what makes a
collision a one-export fix.

**Alternatives considered**: Binding to `127.0.0.1` only — rejected as out of scope for this
feature: port 8000 already exposes the same data to the same network with the same
well-known credentials, so restricting only the new surface would be inconsistent and would
break reaching the stack from another machine.

## Current state of the repository

**Finding**: `.mcp.json` does not exist — absent from the working tree, absent from
`git log --all`, and not matched by `.gitignore`. The `specs/003-server-service/quickstart.md`
that issue #66 cites does not exist either (`003` is `juniper-junos-support`); the live
in-tree reference to the MCP tools is `specs/001-evpn-overlay/quickstart.md:48` plus the
vendored skills, whose tool names take the form `mcp__infrahub__*`
(`.agents/skills/infrahub-analyzing-data/SKILL.md:115` onward).

**Decision**: Create `.mcp.json` with the server registered as `infrahub` (FR-008).

**Rationale**: The skills' hardcoded `mcp__infrahub__*` tool names only resolve if the
server key is exactly `infrahub`. Those skills are vendored and pinned by
`skills-lock.json`, so the config must match them, not the other way round.

## Pin freshness

**Finding**: This repository has no Dependabot or Renovate configuration —
`.github/` holds only `ci.yml`, `sync-docs.yml`, and label configuration. The MCP project
releases roughly weekly (`v1.1.1` through `v1.1.8` in recent history). The repository-owned
`upgrade-infrahub` skill already enumerates the version references it bumps.

**Decision**: No automation. The pin goes stale until someone bumps it.

**Rationale**: An explicit scope call in the feature description. Recorded here so the next
person understands the staleness is chosen, not overlooked. A dependency bot could not read
the tag anyway: it sits inside `${INFRAHUB_MCP_VERSION:-v1.1.7}`, which its Docker parser
does not resolve.

**Alternatives considered**: Adding a step to the `upgrade-infrahub` skill — declined for
this feature, and the cheapest thing to revisit if the pin does drift.
