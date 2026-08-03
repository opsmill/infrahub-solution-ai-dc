---

description: "Task list for Juniper / Junos Vendor Support"
---

# Tasks: Juniper / Junos Vendor Support

**Input**: Design documents from `/specs/003-juniper-junos-support/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md

**Tests**: One unit-test file is touched — and it is **not optional**. `tests/unit/test_vendors.py:32-35`
currently asserts that Juniper is *rejected* and will fail the moment the vendor is added, so fixing it is a
blocking task, not a nice-to-have. No configuration-template test is generated: automated template validation
was explicitly declined (research.md D6); correctness is established by human review (SC-001) and the
`quickstart.md` scenarios.

**Organization**: The spec has a single user story (US1). Phase 2 holds the vendor plumbing that must exist
before anything can be generated; Phase 3 is US1 — the Junos template, its registration, the demo fabric and
its tenant, and the validation that proves the evaluator experience works.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependency on an incomplete task)
- **[US1]**: User Story 1 (setup, foundational and polish tasks carry no story label)

## Path Conventions

Infrahub solution repo: `src/infrahub_solution_ai_dc/` (library), `transforms/` (templates + queries),
`objects/` (data, numbered load order), `.infrahub.yml` (registration), `tests/`.
**No schema files change and no generator files change** — `protocols.py` is NOT regenerated. That constraint
is spec SC-002 and is verified by T033.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Working environment ready.

- [x] T001 Sync dependencies and confirm the working branch: run `uv sync --all-groups --all-extras` from the repo root, on branch `wvd-20260727-add-juniper-support`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Vendor plumbing and demo hardware definitions. Nothing in US1 can be generated or rendered until
these exist. Per [contracts/juniper-registration.md](./contracts/juniper-registration.md) and
[data-model.md](./data-model.md).

- [x] T002 Add `"juniper"` to `SUPPORTED_VENDORS` in `src/infrahub_solution_ai_dc/vendors.py:24` — the entire Python delta for this feature
- [x] T003 Fix `tests/unit/test_vendors.py`: re-point `test_unsupported_manufacturer_raises_naming_device` (lines 32-35) from `"Juniper"` to a still-unsupported manufacturer (e.g. `"Nokia"`), and add `("Juniper", "juniper_devices")` to the happy-path parametrize at lines 14-17
- [x] T004 [P] Add the `juniper_devices` group with `parent: devices` in `objects/01_groups.yml`
- [x] T005 [P] Add `- name: Juniper` in `objects/02_manufacturer.yml`
- [x] T006 [P] Add device types `"QFX5230-64CD"` and `"QFX5120-48Y-8C"`, both with `manufacturer: ["Juniper"]`, in `objects/03_device_type.yml`
- [x] T007 [P] Add the four `TemplateNetworkDevice` entries in `objects/06_device_template.yml` — `juniper-qfx5230-64cd-super-spine-switch`, `juniper-qfx5230-64cd-spine-switch`, `juniper-qfx5120-48y-8c-leaf-switch-compute`, `juniper-qfx5120-48y-8c-leaf-switch-storage` — with the interface/profile split in data-model.md §4, `expand_range: true` on both levels, and exactly one `Loopback0` (role `loopback`) each. Add a YAML comment at the leaf templates noting that the `xe-`/`et-` split is safe **only** because cabling filters by interface role before sorting (research.md D2)

**Checkpoint**: `uv run pytest tests/unit/test_vendors.py` is green and `inv lint` passes.

---

## Phase 3: User Story 1 - A Juniper evaluator sees their hardware and their config (Priority: P1) 🎯 MVP

**Goal**: A Juniper-shop evaluator can trace design intent → generated Juniper switches and cabling → a
rendered Junos startup configuration, using hardware they recognise.

**Independent Test**: Load the solution, generate Fabric-D, and open the `Startup configuration` artifact on
a Fabric-D leaf and on a Fabric-D spine. The leaf shows EVPN/VXLAN with tenant segments; the spine shows the
control plane with no tenant overlay.

### Implementation for User Story 1

The six template tasks all edit `transforms/templates/startup_config_juniper.j2` and are therefore
**strictly sequential** — no `[P]`. Build the file section by section against
[contracts/junos-config-contract.md](./contracts/junos-config-contract.md).

- [x] T008 [US1] Create `transforms/templates/startup_config_juniper.j2` with the preamble — copy lines 1-12 of `startup_config_arista.j2` verbatim (device, fabric, `overlay_asn` fallback, `vns` VRF de-dup namespace), plus `is_rr` from `startup_config_cisco.j2:13` and the anycast-MAC normalisation three-liner from `startup_config_dell.j2:13-15` — then emit the `system { host-name … }` stanza
- [x] T009 [US1] Add the physical-interface section to `transforms/templates/startup_config_juniper.j2`: open `interfaces { }` and emit each `super_spine`/`spine`/`leaf`-role interface as `<name> { description …; disable; unit 0 { family inet { address <CIDR>; } } }`, rendering uncabled ports as present-but-`disable`d with no address (contract A7)
- [x] T010 [US1] Add the loopback and management section to `transforms/templates/startup_config_juniper.j2`: collect the `loopback`-role and `vtep`-role interfaces into a **single** `lo0 { unit 0 … unit 1 … }` stanza, and emit `em0` reusing the loopback IP. Never emit `interface Loopback0`/`Loopback1` literally — role is the discriminator. **This is the one structural departure from the other three templates and the most likely defect** (research.md D4, contract A4)
- [x] T011 [US1] Add `routing-options { router-id; autonomous-system; }` and `protocols { ospf { area 0.0.0.0 { interface lo0.0 { passive; } interface <name>.0 { interface-type p2p; } } } }` to `transforms/templates/startup_config_juniper.j2`
- [x] T012 [US1] Add the EVPN control plane to `transforms/templates/startup_config_juniper.j2`, gated on `overlay_asn is not none` — a `protocols bgp` group EVPN-OVERLAY (type internal, local-address, family evpn signaling, `cluster` only when is_rr, one neighbor block per session) and a `protocols evpn` stanza (encapsulation vxlan, extended-vni-list, vni-options) which is itself leaf-gated. Keep the `sort(attribute="node.peer_device.node.hostname.value")` determinism guard and the remote_as-else-overlay_asn fallback (contract A6, A8)
- [x] T013 [US1] Add the leaf-only tenant overlay to `transforms/templates/startup_config_juniper.j2`, gated on `device.segments.edges`: `irb` units for gateway-bearing segments with `virtual-gateway-address` and the normalised MAC, `switch-options { vtep-source-interface lo0.1; route-distinguisher …; }`, `vlans` (omitting `l3-interface` for gateway-less segments), and `routing-instances` with `irb-symmetric-routing` (contract A2, A5)
- [x] T014 [US1] Register the vendor in `.infrahub.yml`: add the `juniper_device_startup_config` entry to `jinja2_transforms` (after line 91) and the `juniper_startup_configuration` entry to `artifact_definitions` (after line 129), targeting `juniper_devices`, reusing the existing `network_device_startup_config` query, and keeping `artifact_name: "Startup configuration"` identical to the other three
- [x] T015 [P] [US1] Add `Fabric-D` (index 4, 4 super-spines, Juniper super-spine template) with `Pod-D1` (`role: "fabric"`, no spine template), `Pod-D2` and `Pod-D3` in `objects/10_fabric.yml`, mirroring Fabric-B's topology
- [x] T016 [P] [US1] Add the eight Fabric-D racks in `objects/11_rack.yml` per the table in data-model.md §6, mirroring the Fabric-B block at lines 80-143 — **including its two `rack_type`/template mismatches**, so the four fabrics stay comparable
- [x] T017 [P] [US1] Add the `Green` overlay tenant to `objects/12_overlay.yml` per data-model.md §7 — tenant `Green` (`fabric: "Fabric-D"`, `member_of_groups: ["tenants"]`), VRF `green-prod`, and segments `green-web`/`green-app` (routed) plus `green-l2` (L2-only). **Without this, no Juniper leaf renders any overlay config and AS-1 is unsatisfiable** — tenant `Blue` is pinned to Fabric-A (`objects/12_overlay.yml:8`) and Fabric-B/C have no tenant at all. Scope it to Fabric-D only; adding tenants to B/C would change their configs and violate FR-010 (spec FR-011)

### Validation for User Story 1

Per [quickstart.md](./quickstart.md).

- [x] T018 [US1] Run `inv lint` and `inv test`; both must pass before loading
- [x] T019 [US1] Fresh load: `inv destroy && inv start && inv load`, then confirm the Juniper manufacturer, both device types, the `juniper_devices` group (parent `devices`), four object templates with interfaces expanded to Junos names (65 on the spine template, 57 on each leaf template), and the `Green` tenant with its VRF and three segments (quickstart Scenario 1)
- [ ] T020 [US1] Generate Fabric-D and verify 23 devices (4 super-spines, 8 spines, 11 leaves), every one a member of `devices` **and** `juniper_devices` and no other vendor group, with leaves carrying `xe-0/0/0`–`47`, `et-0/0/48`–`55`, `Loopback0` and a runtime `Loopback1` of role `vtep` (quickstart Scenario 2)
- [ ] T021 [US1] Verify cabling: leaf uplinks (`et-0/0/48`+) pair to distinct spine downlinks (`et-0/0/0`–`31`), no `xe-` access port is ever cabled to a spine, no port appears twice, 4 of 8 uplinks cabled per leaf (quickstart Scenario 3 — the Juniper-specific `et-`/`xe-` sort edge case)
- [ ] T022 [US1] Verify every device across all four fabrics has exactly one `Startup configuration` artifact — none with zero, none with two (quickstart Scenario 4, SC-003)
- [ ] T023 [US1] Inspect a Fabric-D leaf config: braces balance, `switch-options`/`vlans`/`routing-instances`/`irb` present, single `lo0` stanza with units 0 and 1, uncabled uplinks `disable`d, and the L2-only segment `green-l2` rendering a `vlans` entry with **no** `l3-interface` and **no** `irb` unit (quickstart Scenario 5, contract A1/A2/A4/A5/A7)
- [ ] T024 [US1] Inspect a Fabric-D spine and super-spine config: `protocols bgp` and `protocols evpn` present, **no** `switch-options`/`vlans`/`routing-instances`/`irb`, `cluster` only on reflecting tiers (quickstart Scenario 6, contract A3/A6)
- [ ] T025 [US1] Verify a zero-line diff on rendered configs for one Cisco, one Arista and one Dell device (quickstart Scenario 7, FR-010)

**Checkpoint**: US1 is complete and independently demonstrable — this is the MVP.

---

## Phase 4: Polish & Cross-Cutting Concerns

**Purpose**: Keep the agent-facing and human-facing documentation truthful, and close the success criteria.

- [x] T026 Update `CONTEXT.md` — de-enumerate the Vendor group entry, and record that `Loopback0`/`Loopback1` are logical names rendered per-vendor with role as the discriminator (**already applied during the grilling session**; verify the three edits are present)
- [x] T027 [P] Update the vendor list in the templates bullet at `AGENTS.md:60` (`startup_config_{cisco,arista,dell}.j2` → include `juniper`)
- [x] T028 [P] Add this feature to the active-features list in `CLAUDE.md`
- [x] T029 [P] Update vendor mentions in `README.md`
- [x] T030 [P] Update vendor lists in `docs/docs/solution-ai-dc/` — `multivendor-config.mdx` is the dedicated page (group table, transform/artifact table, demo-data table, and the `SUPPORTED_VENDORS` prose), plus `overview.mdx`, `installation-setup.mdx`, `demo-guide.mdx`, `evpn-vxlan-overlay.mdx`
- [x] T031 [P] Add `Juniper` to `.vale/styles/spelling-exceptions.txt` (`Junos` is already present at line 49)
- [x] T032 Run the documentation linter over the edited `docs/` pages and confirm it passes. `inv lint` is yamllint + ruff + mypy only and does **not** cover Vale, so nothing else verifies T031 — run Vale directly or via the CI docs job
- [x] T033 Verify SC-002: `git diff --stat main -- schemas/ generators/` must be **empty**. A non-empty diff means the multivendor abstraction leaked and should be recorded as a finding (quickstart Scenario 9)
- [ ] T034 Verify the day-two overlay path reaches Juniper leaves: add a fourth segment to the `Green` tenant's `green-prod` VRF, re-run the overlay generator, and confirm carrying leaves pick it up while Juniper spine configs stay byte-identical (quickstart Scenario 8, contract A8)
- [ ] T035 Verify SC-004: walk Fabric-D design object → generated switches and cabling → rendered Junos configuration, without editing code and running nothing beyond `inv load` plus the generator pipeline (quickstart Scenario 10)
- [ ] T036 **SC-001 review gate**: have a reviewer with production Junos experience review one leaf and one spine config. Brief them with the scoped mandate — Junos syntax, stanza placement and EVPN/VXLAN structure only; management addressing, MTU and AAA/NTP/syslog are repo-wide simplifications and out of scope. Target: zero blocking structural findings

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Setup)** → no dependencies
- **Phase 2 (Foundational)** → depends on Phase 1. **Blocks all of Phase 3.**
- **Phase 3 (US1)** → depends on Phase 2 complete
- **Phase 4 (Polish)** → doc tasks (T026-T032) can start any time; T033-T036 require Phase 3 complete

### Critical ordering constraints

- **T002 before T003** — the test only passes once the vendor is in the allow-list.
- **T005/T006 before T007** — the device templates reference device types by human-friendly ID
  (`["Juniper", "QFX5230-64CD"]`), which must resolve at load time.
- **T007 before T015/T016** — the fabric and racks reference the object templates by name.
- **T015 before T017** — the `Green` tenant references `fabric: "Fabric-D"`, which must exist.
- **T004 before T014** — the artifact definition targets `juniper_devices`; if the group name does not match
  `f"{manufacturer.lower()}_devices"` exactly, artifact targeting silently matches **nothing** rather than
  erroring.
- **T014 before T022** — no registration, no artifacts.
- **T017 before T023** — no tenant, no overlay stanzas to inspect. This is the dependency that makes AS-1
  satisfiable at all.
- **T019 before T020 before T021/T022** — load, then generate, then inspect.
- **T031 before T032** — the linter check only means something once the exception is added.

### Within-file serialization (no [P])

- **T008 → T013** all edit `transforms/templates/startup_config_juniper.j2`. Strictly sequential.
- **T014** is the only `.infrahub.yml` edit (two additive blocks in one task).

### Parallel Opportunities

- **Phase 2**: T004, T005, T006, T007 are four different object files — fully parallel after T002/T003.
- **Phase 3**: T015, T016 and T017 are three different object files, parallel with each other (subject to
  T015 → T017) and with the template chain T008-T013.
- **Phase 4**: T027-T031 are five different documentation files — fully parallel.

---

## Parallel Example: Phase 2

```bash
# After T002 (allow-list) and T003 (test fix), the four data files are independent:
T004  objects/01_groups.yml          # juniper_devices group
T005  objects/02_manufacturer.yml    # Juniper
T006  objects/03_device_type.yml     # QFX5230-64CD, QFX5120-48Y-8C
T007  objects/06_device_template.yml # four device templates
```

## Parallel Example: User Story 1

```bash
# The template chain is sequential, but the demo data is not — run alongside it:
T015  objects/10_fabric.yml   # Fabric-D + Pod-D1/D2/D3
T016  objects/11_rack.yml     # 8 Fabric-D racks
T017  objects/12_overlay.yml  # Green tenant (after T015 — references Fabric-D)
```

---

## Implementation Strategy

### MVP First (User Story 1)

Phases 1-3 are the MVP and the whole feature — there is only one user story. Completing Phase 3 delivers the
full evaluator experience: recognisable Juniper hardware, Junos interface names, correct cabling, and a
rendered Junos startup configuration carrying real tenant overlay on every Juniper leaf.

### Incremental Delivery

1. **Phase 2 alone** is loadable and verifiable — the Juniper manufacturer, device types, group and templates
   all exist, and `inv load` succeeds — but produces no devices and no configs. Not demonstrable on its own,
   which is exactly why the spec keeps the demo fabric inside US1.
2. **Phase 3 through T017** makes the fabric generate with a real tenant. **T018-T025** prove it.
3. **Phase 4** closes the documentation and the four success criteria that need a human or a diff.

### Suggested checkpoints

- After T007: `inv lint` and `uv run pytest tests/unit/test_vendors.py` green.
- After T017: `inv destroy && inv start && inv load` succeeds with no loader errors.
- After T025: the feature is functionally complete; only docs and the review gate remain.

---

## Notes

- **The riskiest task is T010.** Junos models both loopbacks as units of one `lo0`, so the flat
  per-interface loop the other three templates use cannot be copied. A mis-scoped loop here produces
  unbalanced braces and structurally invalid output — a failure mode the flat dialects cannot have, and one
  with no automated test behind it (research.md D6).
- **T003 and T017 are both easy to skip and both fatal.** T003 fails CI. T017 fails silently — everything
  loads and generates, every other check passes, and the leaf config simply has no overlay in it.
- **The computed interface `index` attribute renders `000` for every Junos name.** This is pre-existing and
  vendor-wide — it already does so for every Cisco and Dell interface — and is explicitly out of scope. Do
  not "fix" it here.
- **Fabric-D needs no manual IPAM or ASN entries.** `generate_fabric.py:113` carves a per-fabric `/16` from
  `FabricSupernetPool` and allocates the overlay ASN from a pool, exactly as it did for Fabric-C. The
  OverlayGenerator likewise allocates every VNI, VLAN, route target, subnet and gateway for the `Green`
  tenant — none are declared in the object data.
