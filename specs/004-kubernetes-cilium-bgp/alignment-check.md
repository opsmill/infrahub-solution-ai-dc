# Spec/Ask Alignment Check

**Feature**: `specs/004-kubernetes-cilium-bgp/`
**Date**: 2026-07-29
**Remediation passes used**: 0 of 2

## 1. Source

| | |
|---|---|
| **Source PRD** | [issue #64 comment 5121372690](https://github.com/opsmill/infrahub-solution-ai-dc/issues/64#issuecomment-5121372690) — "PRD: Kubernetes clusters with Cilium BGP", by `dgarros`, 2026-07-29T17:34:25Z |
| **Supporting** | [issue #64 body](https://github.com/opsmill/infrahub-solution-ai-dc/issues/64) — "feat: model Kubernetes clusters spanning multiple servers and render Cilium BGP CRDs" |
| **Retrieval** | Fetched via the authenticated GitHub API (`gh api`), not web fetch — the URL is a GitHub issue comment. Full body retrieved (276 lines), nothing truncated or gated. |
| **Compared against** | `spec.md` at commit `2efb721`, read end to end. |

The check was run because the ask was a URL pointing at a substantive PRD (rule 5a.1).

## 2. Verdict

⚠️ **MINOR DRIFT (proceeding)**

**No functional requirement or success criterion is missing, added, changed, dropped, or
contradicted.** FR-001 through FR-009 and SC-001 through SC-005 are carried across **verbatim**,
including their `*Verify*` clauses. All 13 PRD user stories, all 3 prioritised journeys with their
Given/When/Then acceptance text, all 5 key entities, all 8 edge cases, all 6 assumptions, all 9
out-of-scope items, and all 8 items of the agreed module sketch are present.

Three deviations were found. All three are **additive or corrective rather than reductive**, all three
are documented with their reasoning in the artifacts, and all three arose from the critique phase
verifying a PRD claim rather than from scope creep. None changes what gets built. They are recorded
below in full so the author can overrule any of them.

## 3. Findings

| Severity | Category | PRD reference | Spec reference | Description |
|---|---|---|---|---|
| Minor | changed | Edge Cases — "Zero-member or all-L2 cluster: empty manifest, not an error; **removing the last L3 member correctly withdraws all peering**" | `spec.md` Edge Cases (line 87) + Assumptions (line 134) | The PRD asserts the withdrawal works. The spec keeps the empty-manifest half unchanged but reframes the withdrawal as **Vidra's behaviour, explicitly unverified**. Rationale: whether an empty artifact body makes Vidra delete previously-synced resources or no-op could not be verified without running the operator, so asserting it would be stating something unknown as fact. **FR-005 is untouched and verbatim** — the PRD never carried a withdrawal *requirement*, only this prose claim. The substance is preserved in Assumptions with the reasoning, and a manual check was added to `quickstart.md` step 6. |
| Minor | added | *(absent from the PRD)* | `spec.md` Assumptions (line 133), Out of Scope (line 153), Edge Cases (line 89) | The spec bounds v1 to **one Cilium-consuming cluster per Infrahub branch**. Not in the PRD, which did not consider the delivery path's cardinality. Verified against a running stack rather than reasoned: all artifacts of one definition share one name (the existing cabling plan yields three `CoreArtifact` rows all named `Cabling Plan`), Vidra selects only by name and syncs every match, so a second cluster's manifest would be delivered to the first as well. **This does not contradict FR-003** ("one artifact per Kubernetes cluster"), which presupposes multiple clusters and remains verbatim — *rendering* is correct for any number; only *delivery* cannot disambiguate, and the artifacts state that distinction explicitly. Treated as a necessary clarification: without it the spec would promise behaviour that does not work. |
| Minor | added | *(absent from the PRD)* | `spec.md` Assumptions (line 135), Out of Scope (line 154) | The spec adds an assumption that **service names are valid Kubernetes identifiers**. Not in the PRD. The node selector is used verbatim as a resource name and label value, which Kubernetes constrains more tightly than Infrahub (which requires only uniqueness), so a name with spaces or capitals renders a manifest that fails to apply — contradicting SC-004's "applying with zero edits". Documented as a constraint rather than validated, because adding a fail-loud path would cut against the PRD's own agreed decision that ineligible members are omitted rather than raised. |
| Informational | corrected | Governance Gates — "CI/CD workflow change — none, though **the stale generated-definitions check fails until regeneration**" | `research.md` R6a, `plan.md` Constraints | No such CI check exists. `.github/workflows/ci.yml` has no generated-definitions staleness job. The real ordering gate is **`mypy .`** against the generated `protocols.py`. A factual correction to the PRD, not a scope change — and a sharper constraint, since it drives task ordering. The PRD's companion claim that the Server service integration suite is still skipped **was** verified as accurate. |

### Checked and found aligned

| PRD element | Count | Status |
|---|---|---|
| Functional requirements FR-001..FR-009 | 9 | ✅ verbatim, including `*Verify*` clauses |
| Success criteria SC-001..SC-005 | 5 | ✅ verbatim |
| User stories | 13 | ✅ all covered; mapping recorded in `checklists/requirements.md` (1–5 → US1; 6–8 → US2; 9–10 → US3; 11 → US1 + SC-004; 12 → US4; 13 → US1 scenario 4) |
| Prioritised journeys P1/P2/P3 with Given/When/Then | 3 | ✅ acceptance text verbatim in US1/US2/US3 scenario 1 |
| Key entities | 5 | ✅ all present, including "Requires governance review — new node kind" |
| Edge cases | 8 | ✅ all present (one reframed — see findings) |
| Assumptions | 6 | ✅ all present |
| Out of scope | 9 | ✅ all present, including "no new generator" per ADR-0002 |
| Module sketch (Implementation Decisions) | 8 | ✅ all 8 in `plan.md`; no new generator; no frontend; no SDK/CLI surface |
| Testing Decisions | — | ✅ unit tests only; no integration/contract tests; manual acceptance via `quickstart.md`; the three named unit areas all have tasks |
| Open questions | 2 | ✅ both resolved autonomously, rationale in `checklists/requirements.md`; no `[NEEDS CLARIFICATION]` markers remain |
| Governance gates | 5 | ✅ reflected; "new dependency — none" upheld (`pyyaml` is already an SDK transitive dependency) |

## 4. Action

**Proceed.** No remediation pass was triggered, so the retry budget is untouched (0 of 2 used).

The three minor deviations are surfaced here and in `critiques/critique-20260729-195324.md` for the
author's judgment. Each is independently reversible without touching any requirement:

- To restore the PRD's withdrawal assertion, edit `spec.md` Edge Cases and drop the Assumptions entry.
- To remove the one-cluster bound, drop the Assumptions and Out of Scope entries — but note the
  underlying defect is real and verified, so removing the note does not remove the behaviour.
- To drop the Kubernetes-identifier assumption, remove the Assumptions and Out of Scope entries, or
  convert it into a validation requirement (which would be a genuine scope addition needing approval).
