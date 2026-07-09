---

description: "Task list for Multivendor Per-Vendor Configuration"
---

# Tasks: Multivendor Per-Vendor Configuration

**Input**: Design documents from `/specs/002-multivendor-config/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/

**Tests**: One focused unit test is included for the only unit-testable logic (the vendor-resolution helper).
Everything else is data/registration and is validated end-to-end via `quickstart.md` (no TDD suite requested).

**Organization**: Tasks are grouped by user story. Note the runtime coupling: US1's fail-loudly + vendor-group
artifact targeting means a *full-dataset* load also needs US2 (every device must have a vendor). US1 is still
independently testable by generating **only a vendor-complete fabric** (Fabric-B, which is Dell today).

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependency on an incomplete task)
- **[Story]**: US1 / US2 / US3 (setup, foundational, polish have no story label)

## Path Conventions

Infrahub solution repo: `src/infrahub_solution_ai_dc/` (library), `generators/`, `transforms/`, `objects/`,
`.infrahub.yml` (registration), `tests/`. No schema files change; `protocols.py` is NOT regenerated.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Working environment ready.

- [x] T001 Sync dependencies and confirm the working branch: run `uv sync --all-packages` from the repo root

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The vendor groups that both the generators (membership target) and the artifact definitions
(targets) depend on.

**⚠️ CRITICAL**: US1 cannot be implemented until this phase is complete.

- [x] T002 Add three `CoreStandardGroup`s — `cisco_devices`, `arista_devices`, `dell_devices` — as children of the `devices` group in `objects/01_groups.yml`, per `contracts/vendor-groups.md` (use `parent: devices`, or fall back to `children:` on `devices` if the loader rejects it)

**Checkpoint**: Vendor groups exist and are nested under `devices` — user story work can begin.

---

## Phase 3: User Story 1 - Per-vendor config from a single shared generator (Priority: P1) 🎯 MVP

**Goal**: Each generated device is placed in its `{vendor}_devices` group and renders exactly one startup
config from that vendor's template, using one unforked generator per topology level.

**Independent Test**: Generate a vendor-complete fabric (Fabric-B, Dell today). Confirm every device is a
member of `devices` + exactly one `{vendor}_devices` group, and produces exactly one startup-config artifact
from its vendor's transform. Point a device at a manufacturer-less template → generation fails naming it.

### Tests for User Story 1

- [x] T003 [P] [US1] Unit test for vendor resolution and fail-loudly behavior in `tests/unit/test_vendors.py` (resolves Cisco/Arista/Dell → `{vendor}_devices`; raises a device-naming error when the manufacturer is missing/unknown)

### Implementation for User Story 1

- [x] T004 [P] [US1] Create the shared vendor-resolution helper in `src/infrahub_solution_ai_dc/vendors.py` — resolves `NetworkDevice.device_type.manufacturer.name` → `f"{name.lower()}_devices"`, raising a clear error naming the device when unresolvable, per `contracts/vendor-resolution.md`
- [x] T005 [P] [US1] Create `transforms/templates/startup_config_cisco.j2` as a clone of `transforms/templates/startup_config.j2`
- [x] T006 [P] [US1] Create `transforms/templates/startup_config_arista.j2` as a clone of `transforms/templates/startup_config.j2`
- [x] T007 [P] [US1] Create `transforms/templates/startup_config_dell.j2` as a clone of `transforms/templates/startup_config.j2`
- [x] T008 [US1] In `.infrahub.yml`, remove the `device_startup_config` jinja2_transform and the `startup_configuration` artifact_definition; add the three per-vendor transforms and three artifact_definitions (targets `cisco_devices` / `arista_devices` / `dell_devices`), per `contracts/infrahub-registration.md` (depends on T005–T007)
- [x] T009 [US1] Remove the obsolete `transforms/templates/startup_config.j2` (after T008 no longer references it)
- [x] T010 [P] [US1] Edit `generators/generate_fabric.py` — in the super-spine create+refetch path, add vendor-group membership via `vendors.py` (depends on T002, T004)
- [x] T011 [P] [US1] Edit `generators/generate_pod.py` — add vendor-group membership for spines via `vendors.py` (depends on T002, T004)
- [x] T012 [P] [US1] Edit `generators/generate_rack.py` — add vendor-group membership for leafs via `vendors.py` (depends on T002, T004)

**Checkpoint**: Generating Fabric-B yields Dell devices in `dell_devices`, each with exactly one config from
the Dell transform; an unresolvable device fails loudly. MVP is functional.

---

## Phase 4: User Story 2 - Choose a vendor by choosing a fabric (Priority: P2)

**Goal**: The shipped dataset provides three clean single-vendor fabrics — Fabric-A (Cisco), Fabric-B
(Arista), Fabric-C (Dell) — with no vendor-less devices or templates.

**Independent Test**: Fresh `inv load` + generate each fabric; Fabric-A is 100% Cisco, Fabric-B 100% Arista,
Fabric-C 100% Dell; every template declares a device type; storage-rack leaves build on-vendor.

### Implementation for User Story 2

- [x] T013 [US2] Add `cisco-93400ld-h1-leaf-switch-storage` and `arista-7050x4-48y-4df-leaf-switch-storage` to `objects/06_device_template.yml`, mirroring the `dell-s5232f-on-leaf-switch-storage` port-profile split (spine-facing uplinks + compute-facing access), per `data-model.md` §2
- [x] T014 [US2] Re-vendor Fabric-A to Cisco in `objects/10_fabric.yml` — `super_spine_switch_template: cisco-9364d-gx2-super-spine-switch`, Pod-A2/A3 `spine_switch_template: cisco-9364d-gx2-spine-switch`
- [x] T015 [US2] Re-vendor Fabric-B to Arista in `objects/10_fabric.yml` — `super_spine_switch_template: arista-7060dx5-64s-super-spine-switch`, Pod-B2/B3 `spine_switch_template: arista-7060dx5-64s-spine-switch` (same file as T014)
- [x] T016 [US2] Add Fabric-C (Dell) to `objects/10_fabric.yml`, mirroring today's Fabric-B topology (4 super-spines, Pods C1/C2/C3) with Dell templates (same file as T015)
- [x] T017 [US2] Re-vendor Fabric-A racks to Cisco in `objects/11_rack.yml` — compute leaves → `cisco-93400ld-h1-leaf-switch-compute`, storage leaves (`Rack-A2-4`, `Rack-A3-3`) → `cisco-93400ld-h1-leaf-switch-storage` (needs T013)
- [x] T018 [US2] Re-vendor Fabric-B racks to Arista in `objects/11_rack.yml` — compute → `arista-7050x4-48y-4df-leaf-switch-compute`, storage (`Rack-B3-3`, `Rack-B3-4`) → `arista-7050x4-48y-4df-leaf-switch-storage` (same file as T017; needs T013)
- [x] T019 [US2] Add Fabric-C racks (Dell, mirror Fabric-B rack layout) to `objects/11_rack.yml` using the Dell compute/storage leaf templates (same file as T018)
- [x] T020 [US2] Remove the five vendor-less templates (`spine-switch`, `super-spine-switch`, `Generic Switch`, `leaf-switch-compute`, `leaf-switch-storage`) from `objects/06_device_template.yml` (after T014–T019 removed all references)

**Checkpoint**: All three fabrics are single-vendor; no vendor-less template remains; a full load+generate
completes with zero vendor-resolution errors.

---

## Phase 5: User Story 3 - Iterate one vendor's config in isolation (Priority: P3)

**Goal**: Prove that the per-vendor split is real — editing one vendor template changes only that vendor's
device configs.

**Independent Test**: Edit only `startup_config_dell.j2`, re-render, confirm Cisco/Arista configs are a
zero-line diff.

### Implementation for User Story 3

- [x] T021 [US3] Verify per-vendor isolation (quickstart Scenario 5): make a visible edit to `transforms/templates/startup_config_dell.j2` only, reload the repository, re-render configs, and confirm Cisco and Arista device configs have a zero-line diff; revert the probe edit

**Checkpoint**: Each vendor's config can be iterated independently — the affordance for correct EOS/OS10
syntax (deferred follow-up) is in place.

---

## Phase 6: Polish & Cross-Cutting Concerns

- [x] T022 [P] Add a "Vendor group" entry to `CONTEXT.md` (child of `devices`, one per Manufacturer; "vendor" used interchangeably with "Manufacturer") — the glossary follow-up recorded in the spec
- [x] T023 Run the full `quickstart.md` validation on a fresh stack (`inv destroy && inv start && inv load`, then generate Fabrics A/B/C) — confirms SC-005 (all templates typed), SC-006 (per-fabric vendor), SC-007 (0 vendor-resolution errors)
- [x] T024 Run `inv lint` and `inv test` and resolve any findings

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: no dependencies.
- **Foundational (Phase 2, T002)**: depends on Setup; **blocks US1** (generator membership + artifact targets).
- **US1 (Phase 3)**: depends on Foundational.
- **US2 (Phase 4)**: depends on Foundational only; independent of US1 code, but see runtime coupling below.
- **US3 (Phase 5)**: depends on US1 (needs the three separate templates).
- **Polish (Phase 6)**: after the desired stories are complete.

### Runtime coupling (important)

US1 changes config artifacts to target vendor groups and makes an unresolvable vendor a hard error. A
**full-dataset** load therefore requires US2 (so Fabric-A is no longer vendor-less). To test **US1 alone**,
generate only a vendor-complete fabric (Fabric-B is Dell today). For a clean shippable state, land US1 + US2
together.

### Within-file serialization (no [P])

- `objects/06_device_template.yml`: T013 (add storage) → … → T020 (remove generic) are the same file.
- `objects/10_fabric.yml`: T014 → T015 → T016 are the same file.
- `objects/11_rack.yml`: T017 → T018 → T019 are the same file.
- `.infrahub.yml`: T008 single task.

### Parallel Opportunities

- **US1**: T003 (test), T004 (helper), T005/T006/T007 (three templates) are all different files → parallel.
  Once T002 + T004 are done, T010/T011/T012 (three generators, different files) run in parallel.
- Across stories: after Foundational, US1 and the data edits of US2 touch mostly different files and can be
  progressed by different people (mind the runtime coupling for the final full-load validation).
- **Polish**: T022 (`CONTEXT.md`) is parallel to nothing else it conflicts with.

---

## Parallel Example: User Story 1

```bash
# After T002 (groups) is done, launch the independent US1 pieces together:
Task: "Unit test vendor resolution in tests/unit/test_vendors.py"          # T003
Task: "Create src/infrahub_solution_ai_dc/vendors.py"                       # T004
Task: "Clone startup_config_cisco.j2 / _arista.j2 / _dell.j2"               # T005-T007

# After T004 (helper) is done, the three generator edits run in parallel:
Task: "Add vendor membership in generators/generate_fabric.py"              # T010
Task: "Add vendor membership in generators/generate_pod.py"                 # T011
Task: "Add vendor membership in generators/generate_rack.py"                # T012
```

---

## Implementation Strategy

### MVP First (User Story 1)

1. Phase 1 Setup → Phase 2 Foundational (groups).
2. Phase 3 US1 (helper + templates + registration + generator edits).
3. **STOP and VALIDATE** against Fabric-B (Dell): membership, one-config-per-device, fail-loudly.

### Incremental Delivery

1. Setup + Foundational → groups ready.
2. US1 → validate on Fabric-B → the mechanism is proven (MVP).
3. US2 → re-vendor A/B, add C → three clean single-vendor fabrics; full load+generate is green.
4. US3 → prove per-vendor isolation; unlocks correct-syntax follow-up.
5. Polish → glossary + full quickstart + lint/test.

---

## Notes

- No schema files change → do **not** regenerate `src/infrahub_solution_ai_dc/protocols.py`.
- No generator `.gql` changes → vendor is read via the SDK `client.get(..., include=["device_type"])`.
- Vendor templates start as identical clones; correct EOS/OS10 syntax is deliberately out of scope (US3
  enables that follow-up).
- Apply on a fresh stack; re-vendoring renames interfaces, so in-place stale-interface cleanup is out of scope.
- Commit after each task or logical group; validate at each checkpoint.
