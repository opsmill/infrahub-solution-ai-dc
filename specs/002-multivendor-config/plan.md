# Implementation Plan: Multivendor Per-Vendor Configuration

**Branch**: `wvd-add-overlay` (feature dir `002-multivendor-config`) | **Date**: 2026-07-08 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/002-multivendor-config/spec.md`

**Note**: This plan is grounded in a grilling session in which every design fork was resolved with the user
(nested groups; generator resolves vendor; startup-config-only split; fail-loudly on no vendor; add Cisco &
Arista storage-leaf templates; Fabric-C mirrors today's Fabric-B). It builds directly on the existing
`001-evpn-overlay` feature and reuses that solution's conventions.

## Summary

Make device configuration genuinely per-vendor. Today one Cisco NX-OS template
(`transforms/templates/startup_config.j2`) is rendered onto every device via the flat `devices` group. This
feature (1) adds three vendor device groups (`cisco_devices`, `arista_devices`, `dell_devices`) as **children
of `devices`**, (2) has the existing topology generators resolve each device's manufacturer and add it to its
vendor child group (failing loudly if unresolvable), (3) replaces the single startup-config artifact with
**three per-vendor templates/transforms/artifacts** each targeting a vendor group, and (4) cleans up the
shipped dataset so every device has a manufacturer and each fabric is single-vendor — **Fabric-A → Cisco,
Fabric-B → Arista, Fabric-C (new) → Dell** — removing the five vendor-less templates and adding the two
missing (Cisco/Arista) storage-leaf templates. The three vendor config templates begin as near-identical
clones of today's template; making the EOS/OS10 syntax actually correct is deferred follow-up work.

## Technical Context

**Language/Version**: Python ≥3.11 (target 3.12).

**Primary Dependencies**: Infrahub SDK (`infrahub-sdk[all]`), `invoke`, `uv`, Jinja2 (config templates),
GraphQL (transform/generator queries). Uses core Infrahub `CoreStandardGroup` (with native `parent`/`children`
— confirmed in `infrahub_sdk/protocols.py:143`) and `CoreArtifactDefinition`/`jinja2_transform` registration.

**Storage**: Infrahub graph database via the SDK/GraphQL. Generated configs stored as Infrahub artifacts.

**Testing**: `pytest` — unit tests with mock objects (`tests/unit/`), integration tests against a Dockerized
Infrahub (`tests/integration/`).

**Target Platform**: Linux + Docker Compose (`inv start`).

**Project Type**: Infrahub solution repository — schema (YAML) + generators (Python) + transforms
(Python/Jinja2) + object data (YAML) + artifact definitions, registered in `.infrahub.yml`.

**Performance Goals**: Not latency-sensitive. Generators stay **idempotent** and **scoped**. Vendor
resolution adds one `client.get(..., include=["device_type"])` re-fetch per device (the generators already
re-fetch each device for loopback assignment).

**Constraints**: (1) **No schema change** — vendor groups use core `CoreStandardGroup`; vendor is read from
the existing `NetworkDevice.device_type → NetworkDeviceType.manufacturer` relationship. (2) The generator is
**not forked per vendor** — one class per topology level plus a shared vendor-resolution helper. (3)
Applied via a **fresh load / regeneration** (re-vendoring renames interfaces, so in-place cleanup of stale
interfaces is out of scope). (4) Each device must render **exactly one** startup config → no artifact targets
`devices` after the split. (5) An unresolvable manufacturer is a **hard error** naming the device.

**Scale/Scope**: 0 schema files changed; 3 generators get a small shared post-create step; 1 new shared
helper in `src/`; `transforms/` gains 3 vendor templates + `.infrahub.yml` gains 3 transforms + 3 artifact
defs (and drops 1 of each); `objects/` gains 3 groups, 2 templates, 1 new fabric, loses 5 templates, and
re-vendors 2 existing fabrics.

### Items to verify during implementation (non-blocking — see research.md)

- Whether `CoreStandardGroup` object-file YAML accepts a `parent:` reference (vs setting `children:` on the
  `devices` group). Both map to the same `CoreGroup.parent`/`children` relationship — pick whichever the
  object loader accepts cleanly.
- Whether Infrahub artifact targeting cascades to child-group members (not required — the generator stamps
  vendor-child membership directly; recorded only to close the open question).
- Exact interface-profile split for the two new storage-leaf templates (mirror the Dell storage leaf).

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

`.specify/memory/constitution.md` is the **unpopulated template** — no ratified project gates. The plan
adheres to the solution's documented engineering principles (`AGENTS.md`, `CONTEXT.md`, the ADRs):

- **Design vs Implementation split** — vendor groups/templates are declared as data + registration; the
  generator produces membership as an implementation object. ✅
- **Reuse existing patterns** — `member_of_groups` at device creation, the existing per-device re-fetch, the
  `jinja2_transform` + `artifact_definition` registration path, `CoreStandardGroup`. ✅
- **One shared generator, not forked per vendor.** ✅ (spec FR-002)
- **No disruption to the underlay/overlay build** — no schema change, generators only add group membership. ✅
- **Code style** — Ruff `ALL`, mypy strict, 120-char lines, typed async. ✅

**Gate result: PASS** (no violations → Complexity Tracking left empty).

## Project Structure

### Documentation (this feature)

```text
specs/002-multivendor-config/
├── plan.md              # This file
├── research.md          # Phase 0 — decisions + validated group/artifact/vendor-resolution mechanics
├── data-model.md        # Phase 1 — vendor groups, template inventory, per-vendor fabric assignment
├── quickstart.md        # Phase 1 — end-to-end validation guide
├── contracts/           # Phase 1 — group hierarchy, artifact/transform registration, vendor-resolution contract
│   ├── vendor-groups.md
│   ├── infrahub-registration.md
│   └── vendor-resolution.md
├── checklists/
│   └── requirements.md  # spec-quality checklist (from /speckit-specify)
└── tasks.md             # Phase 2 (/speckit-tasks — NOT created here)
```

### Source Code (repository root)

Touched paths (additive where possible; no schema files change):

```text
src/infrahub_solution_ai_dc/
└── vendors.py                  # NEW — shared vendor→group resolution (raises on unresolved); used by all 3 generators

generators/
├── generate_fabric.py          # EDIT — after super-spine create+refetch, add vendor group (via vendors.py)
├── generate_pod.py             # EDIT — same for spines
└── generate_rack.py            # EDIT — same for leafs
  # (No .gql edits — vendor read via client.get(..., include=["device_type"]).)

transforms/templates/
├── startup_config_cisco.j2     # NEW — clone of startup_config.j2 (initial parity)
├── startup_config_arista.j2    # NEW — clone
├── startup_config_dell.j2      # NEW — clone
└── startup_config.j2           # REMOVE (replaced by the three above)

.infrahub.yml                   # EDIT — replace device_startup_config transform + startup_configuration
                                #        artifact with 3 per-vendor transforms + 3 artifact defs (targets:
                                #        cisco_devices / arista_devices / dell_devices); query unchanged

objects/
├── 01_groups.yml               # EDIT — add cisco_devices/arista_devices/dell_devices (parent: devices)
├── 06_device_template.yml      # EDIT — add cisco + arista storage-leaf templates; remove 5 generic templates
├── 10_fabric.yml               # EDIT — Fabric-A → Cisco templates, Fabric-B → Arista templates; add Fabric-C (Dell, mirrors B)
└── 11_rack.yml                 # EDIT — re-vendor A racks → Cisco, B racks → Arista; add C racks (Dell, mirror B)

tests/                          # NEW/EDIT — unit test for vendors.py resolution + fail-loudly
```

**Structure Decision**: Follow the existing Infrahub solution structure. The change is deliberately
**data + registration heavy and code-light**: the only Python is a small shared `vendors.py` helper and a
three-line addition to each generator's device-creation path. No schema files change, so `protocols.py` is
**not** regenerated.

## Complexity Tracking

> No Constitution Check violations — section intentionally empty.
