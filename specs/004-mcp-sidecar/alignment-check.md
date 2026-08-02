# Spec/Ask Alignment Check: Infrahub MCP server as an always-on sidecar

**Date**: 2026-08-02
**Verdict**: ⚠️ MINOR DRIFT (proceeding)

## Source

The source PRD is the **inline ask** passed to `speckit-specify` — a structured brief with
two prioritised user journeys, seven functional requirements, four success criteria, a
fixed-decisions list, and an explicit out-of-scope list. It originated from an interactive
grilling session over [issue #66](https://github.com/opsmill/infrahub-solution-ai-dc/issues/66)
and supersedes the issue where they differ: the ask carries three verified corrections to the
issue's premises (`.mcp.json` does not exist; the cited `specs/003-server-service/quickstart.md`
does not exist; the newest published image tag is `v1.1.7`).

No URL needed fetching — the PRD was inline, and the issue body was already read directly
with `gh` earlier in the same session.

## Findings

| Severity | Category | PRD reference | Spec reference | Description |
|----------|----------|---------------|----------------|-------------|
| Minor | changed | P1 journey "Then … the user typed no credentials and started no local process"; SC-001 "zero MCP-specific steps" | spec.md Story 1 scenario 1; SC-001; Assumptions | The PRD's zero-step claim is **not achievable**: a project-scoped MCP server requires a one-time approval, and a cloned repository cannot approve its own servers (committed approval settings are ignored in an untrusted folder). SC-001 and the P1 scenario now allow exactly that one action, and an assumption records why. Verified against the client documentation, raised as the critique's single must-address finding (P4/X1). No other part of the criterion was weakened — "no export, no file edit, no local process" all survive. |
| Minor | added | "Design decisions already taken" list | FR-008, FR-009, FR-010 | Three decisions stated as prose in the PRD were promoted to numbered requirements: the client-config server key must be `infrahub`, the session-branch pattern is pinned in the compose override file, and the sidecar starts with no profile or flag. Same content, now testable. No new scope. |
| Minor | added | — | plan.md §4, tasks.md T004, `tests/unit/test_mcp_config.py` | The PRD requested no tests. A unit guard was added on the critique's E5 recommendation, covering only requirements the PRD already states (FR-001, FR-002, FR-008) and running in the repository's existing `pytest tests` suite. Verification of stated requirements, not new capability. |
| Minor | added | "two troubleshooting entries"; docs scope | plan.md docs table; tasks.md T007 | Documentation gained a third troubleshooting entry (image pull failure, from critique E2) and one factual sentence that the endpoint is published on all interfaces like Infrahub's own port (from critique E3). Both are additive detail inside the documentation scope the PRD already granted. |
| None | contradicted | "no caveat text about the committed demo token" | plan.md, tasks.md T009 | Closest call in the set, checked deliberately: the added LAN sentence describes network reachability, never the credential, and carries no warning tone. T009 exists to enforce the rule at review time. Not a contradiction. |

### Checked and clean

- Both PRD journeys are present with the same priorities and semantics.
- FR-001 through FR-007 appear with their wording and strength intact — no MUST softened to
  SHOULD, no scope narrowed.
- SC-002, SC-003 and SC-004 are unchanged.
- All seven out-of-scope items are carried into the spec's Out of Scope section, including
  the deliberate decision to leave the pin without freshness automation.
- Every fixed design decision is reproduced exactly in `plan.md`: the pinned image
  expression, the literal `INFRAHUB_ADDRESS`, `token-passthrough`, the branch pattern, the
  port variable on both sides, the strict-JSON client config with the demo-token fallback,
  no `profiles:`, no `command:`, and `tasks.py` untouched.
- Nothing in the PRD is missing from the spec.

## Action

**Proceed.** Every delta is either a factual correction the PRD could not have known
(the approval step) or additive detail inside scope the PRD already granted. No requirement
was dropped, and no decision was re-litigated. No remediation pass used; the retry budget
of 2 remains untouched.

The one change a reviewer should look at deliberately is SC-001's softening — it is real,
and it is documented here and in the critique rather than absorbed silently.
