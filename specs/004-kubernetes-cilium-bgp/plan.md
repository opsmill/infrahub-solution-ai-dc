# Implementation Plan: Model Kubernetes Clusters Spanning Multiple Servers and Render Cilium BGP CRDs

**Branch**: `dga-release-1.11` | **Date**: 2026-07-29 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/004-kubernetes-cilium-bgp/spec.md`

## Summary

Add a `NetworkKubernetesCluster` design object that groups Server services as **cluster members**, and
render one `application/yaml` artifact per cluster containing the Cilium side of every eligible L3
member's eBGP peering — the mirror image of what the leaf already renders.

The technical shape follows from one verified fact: **`peerAddress` is expressible only in
`CiliumBGPClusterConfig`, not in `CiliumBGPNodeConfigOverride`** (`research.md` R1). Since every member
peers with a different leaf on a different /31, that forces one cluster-config document per member,
rather than one shared config with per-node ASN overrides. The manifest is therefore N cluster configs
plus one shared peer config and one shared advertisement.

The values come from objects that already exist. The **server-side** stored BGP session carries
`local_as` = the member's own ASN and `remote_as` = its leaf's local AS, so one object supplies both
ASNs — and it is the same object the leaf's startup config renders the other half of, which is the
mechanism behind SC-002's "cannot disagree". `peerAddress` comes from walking the member's cabling to
the leaf port's IP, because `NetworkBGPSession` stores no addresses at all (`research.md` R3).

Work splits into a **pure peering module** in the core library (eligibility, ordering, field mapping —
the deep module, no client) and a **thin Python transform** that serialises its records to
multi-document YAML. No new generator: member provisioning stays with the existing `ServerGenerator`
per ADR-0002.

## Technical Context

**Language/Version**: Python >=3.11, target 3.12

**Primary Dependencies**: `infrahub-sdk` (`InfrahubTransform`, `Jinja2Template`), `pyyaml` (already an
SDK transitive dependency — **no new dependency**, matching the PRD's governance gate)

**Storage**: Infrahub graph (schema YAML in `schemas/`, seed objects in `objects/`)

**Testing**: pytest — **unit tests only** in this feature. No integration or contract tests: the Server
service's own integration suite is entirely `@pytest.mark.skip`-marked pending stack foundations
(verified, `research.md` R6b), so adding cluster integration tests would add skipped tests rather than
coverage. Acceptance is manual via `quickstart.md`.

**Target Platform**: Infrahub 1.11.x stack (Docker Compose); the rendered artifact is consumed by the
Vidra operator in a Kubernetes cluster, outside this repository.

**Project Type**: Infrahub solution repository — shared library (`src/`) + generators + transforms +
schema/object data, wired through `.infrahub.yml`.

**Performance Goals**: Not a factor. Rendering is O(members) per cluster on demo-scale data (single
digits). The one property that *does* matter is **checksum stability**: deterministic ordering, so an
unchanged fabric renders a byte-identical manifest and Vidra does not re-sync forever.

**Constraints**:

- `ruff` with `select = ["ALL"]`; `mypy` strict (`disallow_untyped_defs`); line length 120; double
  quotes; 4-space indent; `yamllint` at 140 chars.
- **`mypy .` is the hard ordering gate.** `protocols.py` is generated from the live schema, so schema
  changes + regeneration must land before any code referencing `NetworkKubernetesCluster` or
  `NetworkServer.node_selector`. (The PRD's "stale generated-definitions check" does not exist —
  `research.md` R6a.)
- **The artifact name `Cilium BGP Manifest` is a published contract** with Vidra, typed into
  `InfrahubSync.spec.source.artefactName` in deployed clusters. Renaming it is a breaking change and
  fails silently — Vidra matches on `name__values`, and a no-match is not an error.
- **FR-009 is a design constraint, not just a test**: the `ServerGenerator` must not read the new
  relationship. If the existing Server service unit suite needs an edit, the constraint is broken.

**Scale/Scope**: One new node kind, one new relationship, one new computed attribute, one new group,
one new pure module, one new transform, two new queries, one new schema file, one new/one extended
object file, plus `.infrahub.yml` wiring. Demo dataset: one cluster, four members.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

`.specify/memory/constitution.md` is the **unmodified spec-kit template** — every principle is still a
`[PRINCIPLE_N_NAME]` / `[PRINCIPLE_N_DESCRIPTION]` placeholder. There are therefore **no ratified
project principles to gate against**, and no gate can pass or fail on their content.

In place of that, this plan was checked against the project's actual recorded constraints, which are
the ADRs in `dev/adr/` and the conventions in `AGENTS.md`:

| Recorded constraint | Status |
|---|---|
| **ADR-0002** — standalone generator boundary | **Honoured.** No new generator; provisioning stays with `ServerGenerator`. |
| **ADR-0005** — stored BGP sessions as the render source | **Honoured, and extended in spirit.** The stored session now feeds *both* ends — leaf config and Cilium manifest. |
| **ADR-0006** — server ports as their own kind | **Unaffected.** The cabling walk uses the existing `NetworkEndpoint.link` contract. |
| **ADR-0001** — per-fabric EVPN scope | **Knowingly unconstrained.** Members may span VRFs/Fabrics, unvalidated — an explicit spec decision. |
| `AGENTS.md` — pure helpers in `src/`, thin transforms | **Honoured.** Selection logic in `src/…/clusters.py`; the transform holds none. |
| `AGENTS.md` — `protocols.py` / `*_query.py` are generated | **Honoured.** Regeneration is an explicit ordered step. |

**Post-Phase-1 re-check**: unchanged. The design added no new dependency, no new generator, no
`triggers.yml` change, and no modification to existing Server service behaviour. Nothing in Phase 1
introduced a deviation needing justification.

**Recommendation (out of scope here)**: the constitution is worth filling in, since an unfilled
constitution means every `/speckit-plan` run silently has no gate. Noted rather than acted on — it is
not this feature's work.

## Project Structure

### Documentation (this feature)

```text
specs/004-kubernetes-cilium-bgp/
├── plan.md                              # This file
├── spec.md                              # Feature specification
├── research.md                          # Phase 0 — verified CRD + Vidra contracts, 2 PRD corrections
├── data-model.md                        # Phase 1 — schema deltas + the in-memory peering record
├── quickstart.md                        # Phase 1 — manual acceptance procedure
├── contracts/
│   ├── cilium-manifest-artifact.md      # The published artifact contract (document set + fields)
│   ├── graphql-queries.md               # The transform query + Vidra's fixed ArtifactIDs query
│   └── infrahub-registration.md         # .infrahub.yml / groups / seed wiring
├── checklists/
│   └── requirements.md                  # Spec quality checklist
└── tasks.md                             # Phase 2 output (/speckit-tasks — NOT created here)
```

### Source Code (repository root)

```text
schemas/
├── kubernetes.yml                       # NEW — NetworkKubernetesCluster (CoreArtifactTarget)
└── server.yml                           # EXTEND — service.kubernetes_cluster; server.node_selector

src/infrahub_solution_ai_dc/
├── clusters.py                          # NEW — the deep module: CiliumPeering records,
│                                        #       eligibility, ordering, field mapping. Pure, no client.
└── protocols.py                         # REGENERATED — gains the new kind + computed attribute

transforms/
├── cilium_manifest.py                   # NEW — thin InfrahubTransform; yaml.safe_dump_all
├── cilium_manifest.gql                  # NEW — cluster → members → server/session/cabling
└── cilium_manifest_query.py             # NEW (generated-style) — pydantic response model

queries/
└── artifact_ids.gql                     # NEW — Vidra's ArtifactIDs contract (fixed name/variable)

objects/
├── 09_kubernetes.yml                    # NEW — the cilium-demo cluster
├── 01_groups.yml                        # EXTEND — kubernetes_clusters group
└── 13_servers.yml                       # EXTEND — retrofit members + 2 new L3 workers

tests/unit/
├── test_clusters.py                     # NEW — eligibility, ordering, field mapping
├── test_cilium_manifest.py              # NEW — rendered YAML parsed; document count + fields
└── test_computed_attribute.py           # EXTEND — node_selector template

.infrahub.yml                            # EXTEND — 2 queries, 1 python_transform (+watch), 1 artifact_definition
```

**Structure Decision**: This is an existing Infrahub solution repository with a settled layout, so the
feature slots into it rather than proposing a structure. The one genuinely new location is
`queries/` — a top-level directory for the `ArtifactIDs` query. It belongs to neither `generators/` nor
`transforms/` (it backs no generator and no transform; it is a standalone read surface for an external
consumer), and putting it in either would misfile it. The alternative — parking it in `transforms/` — was
rejected because a future reader would look for a matching transform that does not exist.

The split between `src/infrahub_solution_ai_dc/clusters.py` and `transforms/cilium_manifest.py` is the
PRD's agreed "deep module / thin renderer" boundary: **all** selection and eligibility logic lives in the
pure module so it is unit-testable with plain stubs (mirroring `servers.py` and `overlay.py`), and the
transform only walks the query response and serialises.

## Implementation Phases

Ordering is driven by the `mypy` gate, not by preference.

| # | Step | Why here |
|---|---|---|
| 1 | `schemas/kubernetes.yml` + `schemas/server.yml` edits | Nothing typed can reference the new kind first. |
| 2 | `objects/01_groups.yml` group; `objects/09_kubernetes.yml`; `objects/13_servers.yml` membership | Data the artifact target needs; pure YAML, no type dependency. |
| 3 | `inv load-schema` + regenerate `protocols.py` | **The gate.** Unblocks all typed work; CI `mypy` is red until done. |
| 4 | `src/…/clusters.py` + `tests/unit/test_clusters.py` | The deep module, testable in isolation with stubs. |
| 5 | `test_computed_attribute.py` extension | Independent of 4; the node-selector template. |
| 6 | `transforms/cilium_manifest.gql` + `cilium_manifest_query.py` | The transform's input shape. |
| 7 | `transforms/cilium_manifest.py` + `tests/unit/test_cilium_manifest.py` | Consumes 4 and 6. |
| 8 | `queries/artifact_ids.gql` | Independent; can land any time after 1. |
| 9 | `.infrahub.yml` wiring (queries, transform + `watch:`, artifact definition) | Last — wires the finished pieces. |
| 10 | Manual acceptance per `quickstart.md` | Verification. |

Steps 5 and 8 are independent of the 4 → 6 → 7 chain and can proceed in parallel.

## Key Risks

| Risk | Mitigation |
|---|---|
| Artifact renamed later, silently breaking deployed clusters | Named and flagged as a contract in `contracts/cilium-manifest-artifact.md`, the plan constraints, and `quickstart.md`. |
| `ArtifactIDs` query name/variable/type drifting from Vidra's expectation (`[String]` + `name__values`, not `String` + `name__value`) | Exact document pinned verbatim in `contracts/graphql-queries.md`, with the failure mode (silent empty result) called out. |
| Wrong end of the cabling link selected → the *server's* address rendered as `peerAddress` | Called out explicitly in the query contract; `__typename` discrimination required; a unit test asserts `peerAddress` equals the leaf's address. |
| Non-deterministic member ordering → checksum churn → Vidra re-syncs forever | Ordering by `node_selector` is a stated requirement of the peering module with its own unit test. |
| Clustering leaking into `ServerGenerator` (FR-009) | The generator never reads the new relationship; the existing unit suite must pass with **zero edits** — treated as the check. |
| Empty-cluster case emitting malformed YAML or the two orphan shared documents | Python serialisation rather than Jinja2 (`research.md` R5); FR-005 tested for exactly zero documents. |

## Complexity Tracking

No constitution violations to justify — the constitution has no ratified principles (see Constitution
Check). No deviations from the recorded ADR constraints either, so this table is empty.
