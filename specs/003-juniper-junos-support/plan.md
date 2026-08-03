# Implementation Plan: Juniper / Junos Vendor Support

**Branch**: `wvd-20260727-add-juniper-support` (feature dir `003-juniper-junos-support`) | **Date**: 2026-07-27 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/003-juniper-junos-support/spec.md`

**Note**: This plan is grounded in a grilling session in which every design fork was resolved with the user
(curly-brace Junos syntax; vendor-neutral loopback names mapped in-template; QFX5230-64CD + QFX5120-48Y-8C;
full Fabric-D; manual review instead of automated template validation; model the real 8 uplinks). It is the
fourth vendor added under the `002-multivendor-config` pattern and deliberately changes nothing that feature
established.

## Summary

Add Juniper as the fourth supported vendor. The `002-multivendor-config` feature made vendor support a
**data + registration** concern: a manufacturer, device types, object templates, a `{vendor}_devices` group,
one Jinja2 template, and one transform + artifact-definition pair. This feature exercises that pattern
end-to-end for Juniper and ships a Juniper demo fabric so the capability is visible and inspectable.

The only Python change is **one string added to a tuple**. Everything else is object data, one new Jinja2
template, two `.infrahub.yml` entries, and documentation. No schema file changes, no generator changes, no
GraphQL query changes — which is precisely what spec SC-002 measures.

The substantive work is the Junos template itself. Unlike the three existing dialects it is **hierarchical**,
which forces one genuine structural departure: the flat per-interface loop the other templates use cannot
express `interfaces { lo0 { unit 0 {...} unit 1 {...} } }`, so loopbacks must be collected and emitted as
units of a single `lo0` stanza.

## Technical Context

**Language/Version**: Python ≥3.11 (target 3.12). The Python delta is a single tuple entry.

**Primary Dependencies**: Infrahub SDK (`infrahub-sdk[all]`), `invoke`, `uv`, Jinja2 (config template),
GraphQL (unchanged). No new dependency — the one candidate (a Junos parser for automated validation) was
explicitly rejected with the manual-review decision.

**Storage**: Infrahub graph database via the SDK/GraphQL. Generated configs stored as Infrahub artifacts.

**Testing**: `pytest`. Unit tests only (`tests/unit/test_vendors.py`). **No template test** — see D6. The
existing integration tests are unaffected and must stay green.

**Target Platform**: Linux + Docker Compose (`inv start`).

**Project Type**: Infrahub solution repository — schema (YAML) + generators (Python) + transforms
(Python/Jinja2) + object data (YAML) + artifact definitions, registered in `.infrahub.yml`.

**Performance Goals**: Not latency-sensitive. Fabric-D grows the demo from ~71 to ~94 devices (+32%) and adds
~1,400 interfaces — proportionate to the existing three fabrics, unmeasured against any ceiling (spec
Assumptions).

**Constraints**:

1. **No schema change, no generator change** — spec SC-002. If either is needed, the multivendor abstraction
   leaked and that is a finding, not a licence to edit.
2. **Exactly one artifact per device** — nothing may target the `devices` group; the Juniper artifact
   definition targets `juniper_devices` only.
3. **`transforms/startup_config.gql` is unchanged** — every field a Junos template needs is already queried.
4. **Existing vendors must be untouched** — a zero-line diff on Cisco/Arista/Dell rendered configs.
5. Interface **role**, not interface name, is the discriminator inside the template (`CONTEXT.md`, updated
   this session).

**Scale/Scope**: 0 schema files; 0 generator files; 1 Python line; 1 new Jinja2 template (~150 lines);
2 `.infrahub.yml` entries; 6 object files edited; 1 unit-test file edited; ~8 documentation files.

### Items to verify during implementation (non-blocking — see research.md)

- The computed interface `index` attribute renders `000` for every Junos name. This is **pre-existing and
  vendor-wide** (it already does so for every Cisco and Dell interface) and is explicitly out of scope — but
  confirm it does not *regress* anything, since `NetworkInterface.order_by` depends on it.
- Confirm the Fabric-D super-spine/spine/leaf counts land as expected (`amount_of_spines` defaults to 4 and
  is not set explicitly in the fabric data, matching Fabric-B/C).
- Confirm `inv lint` passes with `Juniper` added to the Vale spelling exceptions.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

`.specify/memory/constitution.md` is the **unpopulated template** (all `[PLACEHOLDER]`) — no ratified project
gates exist. The plan is checked against the solution's documented engineering principles (`AGENTS.md`,
`CONTEXT.md`, the ADRs) instead:

- **Design vs Implementation split** — Juniper templates, device types and the fabric are declared as design
  data; devices, interfaces, cabling and group membership are produced by the existing generators. ✅
- **Reuse existing patterns** — the `{vendor}_devices` group, the `jinja2_transform` + `artifact_definition`
  pair, `member_of_groups` stamping, the shared `network_device_startup_config` query, and the existing
  vendor-neutral interface profiles are all reused unchanged. ✅
- **No generator forking** — `vendors.py` continues to be the single resolution point; the generators are not
  touched. ✅
- **No disruption to underlay/overlay** — additive object data only; existing fabrics unchanged. ✅
- **Code style** — Ruff `ALL`, mypy strict, 120-char lines, yamllint 140-char. The Python delta is one tuple
  entry; the YAML must satisfy yamllint. ✅
- **Governance gates** (`AGENTS.md` names none explicitly; generic list applied) — no schema change, no API
  change, no new dependency, no CI change, no auth change. ✅

**Gate result: PASS** (no violations → Complexity Tracking left empty).

**Post-design re-check (after Phase 1)**: still PASS. The design added no schema change, no generator change,
no new dependency and no new abstraction — the Phase 1 artifacts confirm the change is one tuple entry, one
template, two registration entries and object data. The single structural novelty (collecting loopbacks into
one `lo0` stanza) is contained inside the new template and introduces no cross-cutting concept.

## Project Structure

### Documentation (this feature)

```text
specs/003-juniper-junos-support/
├── plan.md              # This file
├── research.md          # Phase 0 — decisions, rationale, verified mechanics
├── data-model.md        # Phase 1 — Juniper device types, templates, fabric/rack inventory
├── quickstart.md        # Phase 1 — end-to-end validation guide
├── contracts/           # Phase 1
│   ├── juniper-registration.md   # group, vendor list, .infrahub.yml entries
│   └── junos-config-contract.md  # required stanza structure + data surface per device role
├── checklists/
│   └── requirements.md  # spec-quality checklist (from /speckit-specify)
└── tasks.md             # Phase 2 (/speckit-tasks — NOT created here)
```

### Source Code (repository root)

Touched paths — additive throughout; **no schema files and no generator files change**:

```text
src/infrahub_solution_ai_dc/
└── vendors.py                      # EDIT — one line: add "juniper" to SUPPORTED_VENDORS

transforms/templates/
└── startup_config_juniper.j2       # NEW — Junos hierarchical config (see contracts/junos-config-contract.md)
  # transforms/startup_config.gql   — UNCHANGED (shared by all four vendors)

.infrahub.yml                       # EDIT — +1 jinja2_transform, +1 artifact_definition (targets juniper_devices)

objects/
├── 01_groups.yml                   # EDIT — add juniper_devices (parent: devices)
├── 02_manufacturer.yml             # EDIT — add Juniper
├── 03_device_type.yml              # EDIT — add QFX5230-64CD, QFX5120-48Y-8C
├── 06_device_template.yml          # EDIT — add 4 templates (spine, super-spine, leaf-compute, leaf-storage)
├── 10_fabric.yml                   # EDIT — add Fabric-D + Pod-D1/D2/D3
└── 11_rack.yml                     # EDIT — add 8 Fabric-D racks (mirroring Fabric-B/C)

tests/unit/
└── test_vendors.py                 # EDIT — add Juniper happy path; RE-POINT the negative test,
                                    #        which currently asserts Juniper is REJECTED and will fail

CONTEXT.md                          # DONE (3 edits applied during the grilling session)
AGENTS.md                           # EDIT — line 60 vendor list in the templates bullet
CLAUDE.md                           # EDIT — add 003 to the active-features list
README.md                           # EDIT — vendor mentions
docs/docs/solution-ai-dc/*.mdx      # EDIT — vendor lists (multivendor-config.mdx is the dedicated page)
.vale/styles/spelling-exceptions.txt # EDIT — add Juniper (Junos already present)
```

**Structure Decision**: Follow the existing Infrahub solution structure exactly as `002-multivendor-config`
established it. This change is **data + template heavy and code-free** — the single Python line is the whole
code delta, and `protocols.py` is **not** regenerated because no schema changes. The one structural novelty
is inside the new Jinja2 template (hierarchical rather than flat output), which is contained entirely within
that file.

## Complexity Tracking

> No Constitution Check violations — section intentionally empty.
