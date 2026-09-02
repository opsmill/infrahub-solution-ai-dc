# Implementation Plan: NVIDIA Cumulus Linux Vendor Support

**Branch**: `006-cumulus-vendor-support` | **Date**: 2026-09-02 | **Spec**: [spec.md](./spec.md)

**Note**: This plan follows the pattern `002-multivendor-config` established and, most recently,
`005-sonic-vendor-support` exercised end-to-end. It is the sixth vendor added under that pattern and
deliberately changes nothing that `002`/`005` established.

## Summary

Add Cumulus Linux as the sixth supported vendor. The `002-multivendor-config` feature made vendor support a
**data + registration** concern: a manufacturer, device types, object templates, a `{vendor}_devices` group,
one Jinja2 template, and one transform + artifact-definition pair. This feature exercises that pattern
end-to-end for Cumulus Linux and ships a Cumulus demo fabric so the capability is visible and inspectable.

The only Python change is **one string added to a tuple**. Everything else is object data, one new Jinja2
template, two `.infrahub.yml` entries, and documentation. No schema file changes, no generator changes, no
GraphQL query changes — which is precisely what spec SC-002 measures.

The substantive work is the Cumulus template itself. Like SONiC, Cumulus Linux's real configuration surface is
**split across two syntaxes** — Debian's `/etc/network/interfaces` (ifupdown2) for interfaces/bridges/VXLAN,
and FRR's flat CLI for BGP/EVPN — but the ifupdown2 half is structurally distinct from both SONiC's flat
`config` CLI and Junos's arbitrary-depth brace nesting: it is **stanza**-structured (a header line plus a flat
indented attribute block, exactly two levels, never nested stanzas within stanzas). This is a third, milder
structural shape this repository's templates now cover, and it introduces its own narrow discipline: keep
every stanza's attribute lines attached to their own header, never letting one stanza's lines drift into
another's (research.md D5).

## Technical Context

**Language/Version**: Python ≥3.11 (target 3.12). The Python delta is a single tuple entry.

**Primary Dependencies**: Infrahub SDK (`infrahub-sdk[all]`), `invoke`, `uv`, Jinja2 (config template),
GraphQL (unchanged). No new dependency.

**Storage**: Infrahub graph database via the SDK/GraphQL. Generated configs stored as Infrahub artifacts.

**Testing**: `pytest`. Unit tests: `tests/unit/test_vendors.py` (vendor resolution) plus a new
`tests/unit/test_cumulus_device_templates.py` guarding device-template wiring across the eight Cumulus
templates (research.md D10, applying SONiC's D12 precedent from the start). **No template test** — see
research.md D6, matching every existing vendor. The existing integration tests are unaffected and must stay
green.

**Target Platform**: Linux + Docker Compose (`inv start`).

**Project Type**: Infrahub solution repository — schema (YAML) + generators (Python) + transforms
(Python/Jinja2) + object data (YAML) + artifact definitions, registered in `.infrahub.yml`.

**Performance Goals**: Not latency-sensitive. Fabric-F grows the demo from ~117 to ~140 devices (+~20%) and
adds ~1,300 interfaces — proportionate to the existing five fabrics, unmeasured against any ceiling (spec
Assumptions).

**Constraints**:

1. **No schema change, no generator change** — spec SC-002. If either is needed, the multivendor abstraction
   leaked and that is a finding, not a licence to edit.
2. **Exactly one artifact per device** — nothing may target the `devices` group; the Cumulus artifact
   definition targets `cumulus_devices` only.
3. **`transforms/startup_config.gql` is unchanged** — every field a Cumulus template needs is already queried.
4. **Existing vendors must be untouched** — a zero-line diff on Cisco/Arista/Dell/Juniper/SONiC rendered
   configs.
5. Interface **role**, not interface name, is the discriminator inside the template (`CONTEXT.md`).
6. **Interface naming uses Cumulus Linux's real, single `swpN` convention** — sequential front-panel
   numbering, no separator, no alternate naming mode to choose between (research.md D3). This keeps every
   interface declaration a plain `[a-b]` range, the same shape every other vendor's templates already use.

**Scale/Scope**: 0 schema files; 0 generator files; 1 Python line; 1 new Jinja2 template (~110–140 lines);
2 `.infrahub.yml` entries; 6 object files edited; 1 unit-test file edited + 1 new unit-test file (D10);
documentation files.

### Items to verify during implementation (non-blocking — see research.md)

- The computed interface `index` attribute is expected to render the **real port number** (e.g. `033`) for
  `swpN` names, unlike the SONiC/Cisco/Dell/Junos `000` quirk, because `swpN` carries no slash for
  `split_interface` to choke on — confirm this rather than assume it (research.md D3).
- Confirm the Fabric-F super-spine/spine/leaf counts land as expected (`amount_of_spines` defaults to 4 and
  is not set explicitly, matching every prior fabric).
- Confirm `inv lint` passes with `Cumulus`, `Spectrum`, `ifupdown2`, `vxlan`, `swp`, `FRR`, `vtysh` and other
  new terms added to the Vale spelling exceptions (`FRR`/`vtysh` are already present from SONiC).
- Confirm `netutils.interface.sort_interface_list` sorts `swp1`…`swp64` numerically (expected — same
  prefix+bare-integer shape as Arista's already-proven `EthernetN`), not lexicographically.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

`.specify/memory/constitution.md` is the **unpopulated template** (all `[PLACEHOLDER]`) — no ratified project
gates exist, same state `005` found it in. The plan is checked against the solution's documented engineering
principles (`AGENTS.md`, `CONTEXT.md`, the ADRs) instead:

- **Design vs Implementation split** — Cumulus templates, device types and the fabric are declared as design
  data; devices, interfaces, cabling and group membership are produced by the existing generators. ✅
- **Reuse existing patterns** — the `{vendor}_devices` group, the `jinja2_transform` + `artifact_definition`
  pair, `member_of_groups` stamping, the shared `network_device_startup_config` query, and the existing
  vendor-neutral interface profiles are all reused unchanged. ✅
- **No generator forking** — `vendors.py` continues to be the single resolution point; the generators are not
  touched. ✅
- **No disruption to underlay/overlay** — additive object data only; existing fabrics unchanged. ✅
- **Code style** — Ruff `ALL`, mypy strict, 120-char lines, yamllint 140-char. The Python delta is one tuple
  entry; `swpN` interface names keep every device-template YAML line as a short `[a-b]` range, the same shape
  Dell's/SONiC's templates already use, so no yamllint risk. ✅
- **Governance gates** (`AGENTS.md` names none explicitly; generic list applied) — no schema change, no API
  change, no new dependency, no CI change, no auth change. ✅

**Gate result: PASS** (no violations → Complexity Tracking left empty).

**Post-design re-check (after Phase 1)**: still PASS. The design added no schema change, no generator change,
no new dependency and no new abstraction — the Phase 1 artifacts confirm the change is one tuple entry, one
template, two registration entries and object data. The one structural novelty (the ifupdown2 stanza format
in D5) is contained inside the new template and introduces no cross-cutting concept.

## Project Structure

### Documentation (this feature)

```text
specs/006-cumulus-vendor-support/
├── plan.md              # This file
├── research.md          # Phase 0 — decisions, rationale, verified mechanics
├── data-model.md        # Phase 1 — Cumulus device types, templates, fabric/rack inventory
├── quickstart.md        # Phase 1 — end-to-end validation guide
├── contracts/
│   ├── cumulus-registration.md    # group, vendor list, .infrahub.yml entries
│   └── cumulus-config-contract.md # required output structure + data surface per device role
├── checklists/
│   └── requirements.md  # spec-quality checklist (from /speckit-specify)
└── tasks.md              # Phase 2 (/speckit-tasks — NOT created here)
```

### Source Code (repository root)

Touched paths — additive throughout; **no schema files and no generator files change**:

```text
src/infrahub_solution_ai_dc/
└── vendors.py                        # EDIT — one line: add "cumulus" to SUPPORTED_VENDORS

transforms/templates/
└── startup_config_cumulus.j2         # NEW — ifupdown2 interfaces/bridge/VXLAN + FRR (see contracts/cumulus-config-contract.md)
  # transforms/startup_config.gql     — UNCHANGED (shared by all six vendors)

.infrahub.yml                         # EDIT — +1 jinja2_transform, +1 artifact_definition (targets cumulus_devices)

objects/
├── 01_groups.yml                     # EDIT — add cumulus_devices (parent: devices)
├── 02_manufacturer.yml               # EDIT — add Cumulus
├── 03_device_type.yml                # EDIT — add Cumulus-SPECTRUM2, -SPECTRUM3, -SPECTRUM4, -SPECTRUM2-TOR
├── 06_device_template.yml            # EDIT — add 8 templates (spine+super-spine x SPECTRUM2/3/4, leaf-compute, leaf-storage)
├── 10_fabric.yml                     # EDIT — add Fabric-F + Pod-F1(SPECTRUM4)/F2(SPECTRUM2)/F3(SPECTRUM3)
└── 11_rack.yml                       # EDIT — add 8 Fabric-F racks (mirroring Fabric-E, single leaf generation)
# objects/12_overlay.yml              # EDIT — add tenant Amber, VRF amber-prod, 3 segments

tests/unit/
├── test_vendors.py                   # EDIT — add Cumulus happy path to the parametrize; negative test unchanged
└── test_cumulus_device_templates.py  # NEW — device-template wiring guard, all 8 templates (research.md D10)

CONTEXT.md                            # EDIT — Vendor group definition + Flagged-ambiguities entry (D2/D7)
AGENTS.md                             # EDIT — vendor list mentions
CLAUDE.md                             # EDIT — add 006 to the active-features list
README.md                             # EDIT — vendor mentions
docs/docs/solution-ai-dc/*.mdx        # EDIT — vendor lists (multivendor-config.mdx is the dedicated page)
.vale/styles/spelling-exceptions.txt  # EDIT — add Cumulus, Spectrum, ifupdown2, vxlan-related terms not already present
```

**Structure Decision**: Follow the existing Infrahub solution structure exactly as `002-multivendor-config`
established it and `005-sonic-vendor-support` exercised it. This change is **data + template heavy and
code-free** — the single Python line is the whole code delta, and `protocols.py` is **not** regenerated
because no schema changes. The one structural novelty — the ifupdown2 stanza template (research.md D5) — is
contained entirely within the new Jinja2 template.

## Complexity Tracking

> No Constitution Check violations — section intentionally empty.
