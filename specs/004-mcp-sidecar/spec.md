# Feature Specification: Infrahub MCP server as an always-on sidecar

**Feature Branch**: `wvd/chore-mcp-sidecar-passthrough`

**Created**: 2026-08-02

**Status**: Draft

**Input**: Run the Infrahub MCP server as an always-on Docker sidecar in this repo's compose override file, in token-passthrough mode, so agents reach live Infrahub data without a host Python/uv MCP toolchain, without an unpinned server version, and without a user's own credentials in a tracked file. Implements [issue #66](https://github.com/opsmill/infrahub-solution-ai-dc/issues/66).

## User Scenarios & Testing *(mandatory)*

The primary user is someone who has just cloned this repository and wants to ask questions
of live demo data through an agent. Today the bundled skills and
`specs/001-evpn-overlay/quickstart.md:48` assume the Infrahub MCP tools exist, but nothing
in the repository starts a server — so that user must hand-roll a local server process,
which needs a host toolchain, resolves an unpinned version, and puts credentials in a
client config file.

### User Story 1 - Ask live Infrahub questions through an agent (Priority: P1)

After the same start-up commands the Quick start already documents, a user opens their
agent at the repository root and asks a question about the demo fabric. The answer comes
from live Infrahub data. They installed no extra toolchain, exported no variable, and
edited no file.

**Why this priority**: This is the whole point of the change and the smallest slice that
delivers it. It is read-only, so it cannot damage demo data, and a human can verify it in
about two minutes.

**Independent Test**: Bring the stack up with the documented commands, load demo data,
open the agent at the repository root, and ask a question that can only be answered from
Infrahub. Delivers the agent-query capability on its own, with no dependency on Story 2.

**Acceptance Scenarios**:

1. **Given** a fresh clone, no personal API token exported, no host MCP toolchain, and the
   stack brought up and loaded with the documented commands, **When** the user opens their
   agent at the repository root, approves the server at the one-time prompt, and asks a
   question about the demo fabric, **Then** the agent lists the Infrahub MCP server as
   connected, answers from live Infrahub data, and the user has typed no credentials,
   exported no variable, edited no file, and started no local process.
2. **Given** the stack is running but demo data has not been loaded, **When** the user asks
   the same question, **Then** the tools respond successfully with empty results rather
   than a connection or authentication error.

---

### User Story 2 - Create data and open a proposed change through an agent (Priority: P2)

A user asks the agent to create an object and open a proposed change for review. The write
lands on an isolated, identifiable session branch under the permissions of whichever
credential the client presented, and a proposed change appears for a human to review.
Nothing is merged automatically.

**Why this priority**: Writing is the natural next thing a user asks for once reading works,
and it exercises a path Story 1 does not — the client's own credential reaching Infrahub's
permission model, and the session-branch plus proposed-change review loop. It ships on the
same server as Story 1 but needs its own verification. The consumer here is an ad-hoc agent
request; no bundled workflow in this repository drives it.

**Independent Test**: With the stack running and demo data loaded, ask the agent to create
one object and open a proposed change; confirm the session branch and the proposed change
exist and that nothing merged.

**Acceptance Scenarios**:

1. **Given** the sidecar running with the demo credential and demo data loaded, **When**
   the user asks the agent to create an object and open a proposed change, **Then** an
   identifiable session branch is created, the write is recorded on that branch under the
   presented credential's permissions, and a proposed change targeting the default branch
   is visible for review with nothing merged.
2. **Given** an agent session that has already written to its session branch, **When** the
   proposed change is opened, **Then** the session branch carries data changes only and
   creates no branch in any git repository.

---

### Edge Cases

- **The published port is already in use on the host** (a second stack, a stray
  container): a single documented variable must move both the published port and the
  address the client uses, so recovery is one export and no file edit.
- **The user's shell already exports an API token for a different Infrahub instance**:
  every tool call fails closed with an authentication error rather than silently querying
  the wrong instance or falling back to a shared server-side credential.
- **Infrahub is still starting**: the sidecar must not accept traffic before Infrahub is
  healthy, so a user never sees a half-working server.
- **Demo data not loaded yet**: tools succeed and return empty results (covered by
  Story 1, scenario 2).
- **Agent sessions accumulate session branches and open proposed changes**: this residue
  is expected on a disposable demo stack, is confined to an identifiable branch namespace,
  and is removed when the stack is destroyed.
- **The endpoint is reachable from the local network**: accepted — the stack already
  publishes Infrahub itself the same way, with the same well-known demo credentials
  guarding the same data.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The MCP server container MUST NOT be configured with any Infrahub
  credential — no API token, username, or password in the compose override file.
- **FR-002**: Committed client configuration MUST source the token from the
  `INFRAHUB_API_TOKEN` environment variable; any inline fallback MUST grant nothing beyond
  a local throwaway demo stack.
- **FR-003**: Documentation MUST show `export INFRAHUB_API_TOKEN=<token>` as the override
  mechanism, as a mechanical instruction with no commentary about secrets.
- **FR-004**: The server image MUST be pinned to an explicit published version,
  overridable through `INFRAHUB_MCP_VERSION`, and MUST NOT track a floating tag.
- **FR-005**: A newcomer MUST reach working MCP tools with no host MCP toolchain and no
  manual credential step.
- **FR-006**: An agent MUST be able to write and open a proposed change through the
  sidecar, executing under the permissions of the credential the client presented.
- **FR-007**: One variable, `INFRAHUB_MCP_PORT`, MUST move both the published host port
  and the client's configured address together.
- **FR-008**: The committed client configuration MUST register the server under the name
  `infrahub`, so the `mcp__infrahub__*` tool names used by the bundled skills resolve.
- **FR-009**: The session-branch naming pattern MUST be pinned in the compose override
  file rather than inherited from an image default, so agent-created branches are
  identifiable and a version bump cannot rename them.
- **FR-010**: The sidecar MUST start with the rest of the stack under the existing start
  command, with no additional flag, profile, or task.

### Key Entities

- **MCP sidecar service**: the containerised Infrahub MCP server in the compose override
  file, reaching Infrahub over the internal container network; holds no credentials.
- **Committed client configuration**: the repository-root MCP client config that points at
  the sidecar and carries the token as an environment-variable reference.
- **Session branch**: the isolated, identifiable Infrahub branch an agent creates for its
  own writes; data-only, reviewed through a proposed change.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A newcomer following the existing Quick start reaches a working Infrahub MCP
  read call with no extra command, no export, and no file edit — the only MCP-specific
  action is approving the server once when the agent asks on first run.
- **SC-002**: The only Infrahub credentials present in tracked files are the public demo
  defaults already shipped with the stack; a user's own token never needs to enter a
  tracked file.
- **SC-003**: The server version in use is fully determined by repository contents plus
  documented environment variables — the same repository state yields the same version for
  two different people, or the same person a week apart.
- **SC-004**: Story 1 completes on a machine with no host MCP toolchain installed.

## Assumptions

- The newest published server image version is `v1.1.7` (image tags carry a `v` prefix).
  Version 1.1.8 exists on the package index but its image is not in the registry yet.
- That version is compatible with the Infrahub version this repository runs (1.10.0): the
  server tests against Infrahub 1.10 or newer, and its two tools that require Infrahub
  1.10+ are satisfied.
- Claude Code is the primary client: a config file at the repository root is auto-detected,
  and `${VAR}` / `${VAR:-default}` expansion works in both the address and the headers.
- Detection is not approval: a server defined in a project-scoped config waits at
  "pending approval" until the user accepts it in an interactive session, and a cloned
  repository cannot approve its own servers — approval settings committed to the repository
  are ignored in a folder the user has not trusted. Every user therefore approves the server
  once, per clone. This is the single step SC-001 allows for.
- The demo stack is disposable; a user's own token value lives in `.envrc`, which is
  already gitignored.
- Session branches are data-only upstream (no git branch is created), so they do not
  interact with this repository's git-import branch-name rule.
- `.mcp.json` does not exist in this repository today — no history on any branch and not
  gitignored — so this feature creates it.
- The client config format is strict JSON and cannot carry comments.

## Out of Scope

- Automated freshness for the pinned version: no dependency bot, and no step added to the
  `upgrade-infrahub` skill. The pin goes stale until someone bumps it.
- External-identity and read-only operating modes beyond exposing their configuration
  knobs with defaults.
- Restricting the published port to the loopback interface.
- Glossary entries in `CONTEXT.md`.
- Any change to the vendored `infrahub-*` skills, which are pinned by `skills-lock.json`.
- Any caveat or warning text about the committed demo credential.
- Wiring for non-Claude clients beyond what the documentation shows.
