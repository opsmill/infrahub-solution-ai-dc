# Implementation Plan: SONiC Vendor Support

**Branch**: `005-sonic-vendor-support` | **Date**: 2026-08-27 | **Spec**: [spec.md](./spec.md)

**Note**: This plan follows the pattern `002-multivendor-config` established and `003-juniper-junos-support`
exercised end-to-end. It is the fifth vendor added under that pattern and deliberately changes nothing that
`002`/`003` established.

## Summary

Add SONiC as the fifth supported vendor. The `002-multivendor-config` feature made vendor support a **data +
registration** concern: a manufacturer, device types, object templates, a `{vendor}_devices` group, one
Jinja2 template, and one transform + artifact-definition pair. This feature exercises that pattern end-to-end
for SONiC and ships a SONiC demo fabric so the capability is visible and inspectable.

The only Python change is **one string added to a tuple**. Everything else is object data, one new Jinja2
template, two `.infrahub.yml` entries, and documentation. No schema file changes, no generator changes, no
GraphQL query changes — which is precisely what spec SC-002 measures.

The substantive work is the SONiC template itself. Unlike the four existing dialects, SONiC's real
configuration surface is **split across two flat syntaxes** — a Linux-style `config` CLI for
interfaces/VLANs/VXLAN, and FRR's Cisco-like flat CLI for BGP/EVPN — rather than a single dialect. This is a
milder structural departure than Junos's hierarchy (no brace-nesting risk), but it introduces its own
discipline: never letting one syntax's verbs leak into the other's section. SONiC also supports two distinct
interface-naming modes; this feature uses the sequential, front-panel-friendly **alias** mode (`Eth1/N`)
rather than the lane-indexed default mode, which keeps every device-template declaration a plain `[a-b]`
range — the same shape every other vendor's templates already use (research.md D3).

## Technical Context

**Language/Version**: Python ≥3.11 (target 3.12). The Python delta is a single tuple entry.

**Primary Dependencies**: Infrahub SDK (`infrahub-sdk[all]`), `invoke`, `uv`, Jinja2 (config template),
GraphQL (unchanged). No new dependency.

**Storage**: Infrahub graph database via the SDK/GraphQL. Generated configs stored as Infrahub artifacts.

**Testing**: `pytest`. Unit tests: `tests/unit/test_vendors.py` (vendor resolution) plus a new
`tests/unit/test_sonic_device_templates.py` guarding device-template wiring across the eight SONiC templates
(research.md D12). **No template test** — see research.md D6, matching every existing vendor; D12 is a
distinct, narrower guard on object-data shape, not rendered-config content. The existing integration tests
are unaffected and must stay green.

**Target Platform**: Linux + Docker Compose (`inv start`).

**Project Type**: Infrahub solution repository — schema (YAML) + generators (Python) + transforms
(Python/Jinja2) + object data (YAML) + artifact definitions, registered in `.infrahub.yml`.

**Performance Goals**: Not latency-sensitive. Fabric-E grows the demo from ~94 to ~117 devices (+24%) and
adds ~1,300 interfaces — proportionate to the existing four fabrics, unmeasured against any ceiling (spec
Assumptions).

**Constraints**:

1. **No schema change, no generator change** — spec SC-002. If either is needed, the multivendor abstraction
   leaked and that is a finding, not a licence to edit.
2. **Exactly one artifact per device for the other four vendors; exactly two for SONiC** — nothing may target
   the `devices` group; both SONiC artifact definitions (config-CLI + FRR) target `sonic_devices` only
   (FR-006, revised — see `contracts/sonic-registration.md`).
3. **`transforms/startup_config.gql` is unchanged** — every field a SONiC template needs is already queried.
4. **Existing vendors must be untouched** — a zero-line diff on Cisco/Arista/Dell/Juniper rendered configs.
5. Interface **role**, not interface name, is the discriminator inside the template (`CONTEXT.md`).
6. **Interface naming uses SONiC's alias (front-panel) mode, `Eth1/N`** — sequential per port, not the
   alternative lane-indexed default-mode naming (research.md D3). This keeps every interface declaration a
   plain `[a-b]` range, avoiding both an authenticity trade-off and a yamllint line-length risk an earlier
   draft hit (research.md D10).

**Scale/Scope**: 0 schema files; 0 generator files; 1 Python line; 2 new Jinja2 templates (config-CLI + FRR,
~50 and ~90 lines); 4 `.infrahub.yml` entries (2 transforms, 2 artifact definitions); 6 object files edited;
1 unit-test file edited + 1 new unit-test file (D12); documentation files.

### Items to verify during implementation (non-blocking — see research.md)

- The computed interface `index` attribute is expected to render `000` for SONiC's `Eth1/N` alias names, the
  same pre-existing behaviour Cisco/Dell/Junos already have (not Arista's exception) — confirm this rather
  than assume it, since `NetworkInterface.order_by` depends on it (research.md, final note).
- Confirm the Fabric-E super-spine/spine/leaf counts land as expected (`amount_of_spines` defaults to 4 and is
  not set explicitly in the fabric data, matching every prior fabric).
- Confirm `inv lint` passes with `SONiC`, `Tomahawk`, `Trident`, `Broadcom`, `FRR`, `vtysh` and other new terms added to the Vale
  spelling exceptions, alongside the existing `Juniper`/`Junos` entries.
- Confirm SONiC devices actually default to (or can be assumed to run in) `interface_naming_mode: alias` —
  the rendered `config` CLI lines should be consistent with that mode throughout, not mix alias names with
  default-mode assumptions.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

`.specify/memory/constitution.md` is the **unpopulated template** (all `[PLACEHOLDER]`) — no ratified project
gates exist, same state `003` found it in. The plan is checked against the solution's documented engineering
principles (`AGENTS.md`, `CONTEXT.md`, the ADRs) instead:

- **Design vs Implementation split** — SONiC templates, device types and the fabric are declared as design
  data; devices, interfaces, cabling and group membership are produced by the existing generators. ✅
- **Reuse existing patterns** — the `{vendor}_devices` group, the `jinja2_transform` + `artifact_definition`
  pair, `member_of_groups` stamping, the shared `network_device_startup_config` query, and the existing
  vendor-neutral interface profiles are all reused unchanged. ✅
- **No generator forking** — `vendors.py` continues to be the single resolution point; the generators are not
  touched. ✅
- **No disruption to underlay/overlay** — additive object data only; existing fabrics unchanged. ✅
- **Code style** — Ruff `ALL`, mypy strict, 120-char lines, yamllint 140-char. The Python delta is one tuple
  entry; alias-mode interface names (D3) keep every device-template YAML line as a short `[a-b]` range, the
  same shape Dell's existing template already uses, so no yamllint risk. ✅
- **Governance gates** (`AGENTS.md` names none explicitly; generic list applied) — no schema change, no API
  change, no new dependency, no CI change, no auth change. ✅

**Gate result: PASS** (no violations → Complexity Tracking left empty).

**Post-design re-check (after Phase 1)**: still PASS. The design added no schema change, no generator change,
no new dependency and no new abstraction — the Phase 1 artifacts confirm the change is one tuple entry, one
template, two registration entries and object data. The one structural novelty (the two-syntax config split
in D5) is contained inside the new template and introduces no cross-cutting concept; the interface-naming
question (D3) resolved to the same object-data shape every other vendor already uses.

## Project Structure

### Documentation (this feature)

```text
specs/005-sonic-vendor-support/
├── plan.md              # This file
├── research.md          # Phase 0 — decisions, rationale, verified mechanics
├── data-model.md        # Phase 1 — SONiC device types, templates, fabric/rack inventory
├── quickstart.md        # Phase 1 — end-to-end validation guide
├── contracts/            # Phase 1
│   ├── sonic-registration.md    # group, vendor list, .infrahub.yml entries
│   └── sonic-config-contract.md # required output structure + data surface per device role
├── checklists/
│   └── requirements.md  # spec-quality checklist (from /speckit-specify)
└── tasks.md              # Phase 2 (/speckit-tasks — NOT created here)
```

### Source Code (repository root)

Touched paths — additive throughout; **no schema files and no generator files change**:

```text
src/infrahub_solution_ai_dc/
└── vendors.py                      # EDIT — one line: add "sonic" to SUPPORTED_VENDORS

transforms/templates/
├── startup_config_sonic.j2         # NEW — SONiC config CLI (see contracts/sonic-config-contract.md)
└── startup_config_sonic_frr.j2     # NEW — FRR routing config (see contracts/sonic-config-contract.md)
  # transforms/startup_config.gql   — UNCHANGED (shared by all six templates)

.infrahub.yml                       # EDIT — +2 jinja2_transforms, +2 artifact_definitions (both target sonic_devices)

objects/
├── 01_groups.yml                   # EDIT — add sonic_devices (parent: devices)
├── 02_manufacturer.yml             # EDIT — add SONiC
├── 03_device_type.yml              # EDIT — add SONiC-T4, SONiC-T5, SONiC-T6, SONiC-TD4
├── 06_device_template.yml          # EDIT — add 8 templates (spine+super-spine x T4/T5/T6, leaf-compute, leaf-storage)
├── 10_fabric.yml                   # EDIT — add Fabric-E + Pod-E1(T6)/E2(T4)/E3(T5)
└── 11_rack.yml                     # EDIT — add 8 Fabric-E racks (mirroring Fabric-D, single leaf generation)
# objects/12_overlay.yml            # EDIT — add tenant Purple, VRF purple-prod, 3 segments

tests/unit/
├── test_vendors.py                 # EDIT — add SONiC happy path to the parametrize; negative test unchanged
└── test_sonic_device_templates.py  # NEW — device-template wiring guard, all 8 templates (research.md D12)

CONTEXT.md                          # DONE — Vendor group definition + one Flagged-ambiguities entry (D2/D7)
AGENTS.md                           # EDIT — vendor list mentions
CLAUDE.md                           # EDIT — add 005 to the active-features list
README.md                           # EDIT — vendor mentions
docs/docs/solution-ai-dc/*.mdx      # EDIT — vendor lists (multivendor-config.mdx is the dedicated page)
.vale/styles/spelling-exceptions.txt # EDIT — add SONiC, Tomahawk, Trident, Broadcom, FRR, vtysh, NVO
```

**Structure Decision**: Follow the existing Infrahub solution structure exactly as `002-multivendor-config`
established it and `003-juniper-junos-support` exercised it. This change is **data + template heavy and
code-free** — the single Python line is the whole code delta, and `protocols.py` is **not** regenerated
because no schema changes. The one structural novelty — the two-dialect template (research.md D5) — is
contained entirely within the new Jinja2 template. Interface naming (research.md D3) deliberately uses
SONiC's alias mode so the object-data shape stays identical to every other vendor's — no separate novelty to
contain there.

## Complexity Tracking

> No Constitution Check violations — section intentionally empty.
