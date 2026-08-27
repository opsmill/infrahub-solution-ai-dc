---

description: "Task list for SONiC Vendor Support"
---

# Tasks: SONiC Vendor Support

**Input**: Design documents from `/specs/005-sonic-vendor-support/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md

**Tests**: Two unit-test files are touched. `tests/unit/test_vendors.py` needs a SONiC happy-path case added
(not fatal if skipped — the negative-path fixture is unaffected). `tests/unit/test_sonic_device_templates.py`
is **new** and **not optional**: it guards the eight near-identical device templates against a
copy-paste/wiring error (research.md D12, retargeted from a pre-implementation critique finding). No
configuration-template test is generated: automated template validation was explicitly declined (research.md
D6); correctness is established by human review (SC-001) and the `quickstart.md` scenarios.

**Organization**: The spec has a single user story (US1). Phase 2 holds the vendor plumbing — including all
four device types and all eight device templates — that must exist before anything can be generated; Phase 3
is US1: the SONiC template (two syntaxes, one artifact), its registration, the three-chipset-generation demo
fabric and its tenant, and the validation that proves the evaluator experience works.

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

- [x] T001 Sync dependencies and confirm the working branch: run `uv sync --all-groups --all-extras` from the repo root, on branch `005-sonic-vendor-support`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Vendor plumbing and all four chipset-generation device-type/template definitions. Nothing in US1
can be generated or rendered until these exist. Per
[contracts/sonic-registration.md](./contracts/sonic-registration.md) and [data-model.md](./data-model.md).

- [x] T002 Add `"sonic"` to `SUPPORTED_VENDORS` in `src/infrahub_solution_ai_dc/vendors.py` — the entire Python delta for this feature
- [x] T003 Add `("SONiC", "sonic_devices")` to the happy-path parametrize in `tests/unit/test_vendors.py`; confirm the existing negative-path fixture (a still-unsupported manufacturer) is unaffected — no edit needed there since only `"sonic"` is being added
- [x] T004 [P] Add the `sonic_devices` group with `parent: devices` in `objects/01_groups.yml`
- [x] T005 [P] Add `- name: SONiC` in `objects/02_manufacturer.yml`
- [x] T006 [P] Add four device types in `objects/03_device_type.yml` — `SONiC-T4`, `SONiC-T5`, `SONiC-T6`, `SONiC-TD4`, all `manufacturer: ["SONiC"]` — with the inline chipset/capacity/breakout-lane comment for each from data-model.md §3 (research.md D7, D11)
- [x] T007 [P] Add eight `TemplateNetworkDevice` entries in `objects/06_device_template.yml` — `sonic-t4-super-spine-switch`, `sonic-t4-spine-switch`, `sonic-t5-super-spine-switch`, `sonic-t5-spine-switch`, `sonic-t6-super-spine-switch`, `sonic-t6-spine-switch`, `sonic-td4-leaf-switch-compute`, `sonic-td4-leaf-switch-storage` — with the interface/profile split in data-model.md §4 (`Eth1/[1-32]`/`Eth1/[33-64]` split for spines, `Eth1/[1-64]` for super-spines, `Eth1/[1-48]`/`Eth1/[49-54]` for leaves), `expand_range: true` on both levels, and exactly one `Loopback0` (role `loopback`) each. The three spine templates and three super-spine templates are byte-identical except `template_name` and `device_type` — copy-paste-rename, not redesign (data-model.md §4)
- [x] T008 Create `tests/unit/test_sonic_device_templates.py` per research.md D12: for all eight templates from T007, assert `device_type` matches the intended chipset/role pairing, and assert `infrahub_sdk.spec.range_expansion.range_expansion` on each declared interface pattern expands to the expected count and first/last name (65 total interfaces for every spine/super-spine template, 55 for both leaf templates)

**Checkpoint**: `uv run pytest tests/unit/test_vendors.py tests/unit/test_sonic_device_templates.py` is green and `inv lint` passes.

---

## Phase 3: User Story 1 - A SONiC evaluator sees their hardware and their config (Priority: P1) 🎯 MVP

**Goal**: A SONiC-shop evaluator can trace design intent → generated SONiC switches (spanning three chipset
generations) and cabling → a rendered SONiC startup configuration, using hardware and syntax they recognise.

**Independent Test**: Load the solution, generate Fabric-E, and open the `Startup configuration` artifact on
a Fabric-E leaf and on a spine from each of the three pods (T4/T5/T6). The leaf shows EVPN/VXLAN with tenant
segments; every spine/super-spine shows the control plane with no tenant overlay, identically structured
regardless of chipset generation.

### Implementation for User Story 1

The template tasks all edit `transforms/templates/startup_config_sonic.j2` and are therefore **strictly
sequential** — no `[P]`. Build the file section by section against
[contracts/sonic-config-contract.md](./contracts/sonic-config-contract.md).

- [x] T009 [US1] Create `transforms/templates/startup_config_sonic.j2` with the preamble — copy the `device`/`fabric`/`overlay_asn` fallback and `vns` VRF de-dup namespace from `startup_config_arista.j2`, plus `is_rr` and the anycast-MAC normalisation three-liner reused from the existing templates — then emit the always-present SONiC `config` CLI section: `config interface description`/`startup`/`shutdown`/`ip add` for every `super_spine`/`spine`/`leaf`/`server`-role interface (unfiltered loop, one command per line, uncabled ports still get description+shutdown per contract A7), plus `config interface ip add Loopback0 <loopback_ip>/32`
- [x] T010 [US1] Add the FRR EVPN control-plane section to `transforms/templates/startup_config_sonic.j2`, gated on `overlay_asn is not none`: `router bgp <asn>` / `bgp router-id` / `no bgp default ipv4-unicast` / one `neighbor ... remote-as ...` + `update-source Loopback0` pair per session (sorted by peer hostname, contract A8) / `address-family l2vpn evpn` with `neighbor ... activate`, `neighbor ... route-reflector-client` only when `is_rr` and the session has `rr_client` (contract A6), and `advertise-all-vni`
- [x] T011 [US1] Add the leaf-only tenant overlay's SONiC `config` CLI section, gated on `device.segments.edges`: `config vlan add <vlan_id>` and `config vxlan map add vtep1 <vlan_id> <l2vni>` for every segment; `config interface ip add Vlan<vlan_id> <gateway CIDR>` and `config interface vrf bind Vlan<vlan_id> <vrf name>` **only** for gateway-bearing segments (contract A5 — the L2-only segment gets the first two lines and neither of these); `config vxlan add vtep1 <vtep-role interface's address>` and `config vxlan evpn_nvo add nvo1 vtep1` once per device (contract A4 — never the loopback-role address)
- [x] T012 [US1] Add the leaf-only tenant overlay's FRR section to `transforms/templates/startup_config_sonic.j2`: per-segment `vni <l2vni> / rd <loopback_ip>:<vlan_id> / route-target both <route_target>` inside `address-family l2vpn evpn`, plus a top-level `vrf <name> / vni <l3vni> / exit-vrf` block per materialised VRF (contract A2)
- [x] T013 [US1] Add a one-line comment banner at the top of each syntax section in `transforms/templates/startup_config_sonic.j2` (`! --- SONiC config CLI ... ---` / `! --- FRR routing config ... ---`) naming how that section is actually applied on a real device — satisfies critique P2 (the two-syntax artifact should read as deliberate, not sloppy, to a SONiC-savvy evaluator)
- [x] T014 [US1] Register the vendor in `.infrahub.yml`: add the `sonic_device_startup_config` entry to `jinja2_transforms` (after the `juniper_device_startup_config` entry) and the `sonic_startup_configuration` entry to `artifact_definitions` (after `juniper_startup_configuration`), targeting `sonic_devices`, reusing the existing `network_device_startup_config` query, and keeping `artifact_name: "Startup configuration"` identical to the other four
- [x] T015 [P] [US1] Add `Fabric-E` (index 5, 4 super-spines, `super_spine_switch_template: sonic-t6-super-spine-switch`) with `Pod-E1` (`role: "fabric"`, no spine template), `Pod-E2` (`spine_switch_template: sonic-t4-spine-switch`) and `Pod-E3` (`spine_switch_template: sonic-t5-spine-switch`) in `objects/10_fabric.yml`, mirroring Fabric-D's topology (data-model.md §5 — three chipset generations, one per pod, research.md D8)
- [x] T016 [P] [US1] Add the eight Fabric-E racks in `objects/11_rack.yml` per the table in data-model.md §6, mirroring the Fabric-D block — **including its two `rack_type`/template mismatches** — all using the single `sonic-td4-leaf-switch-{compute,storage}` templates regardless of which pod (and therefore which spine generation) they attach to
- [x] T017 [P] [US1] Add the `Purple` overlay tenant to `objects/12_overlay.yml` per data-model.md §7 — tenant `Purple` (`fabric: "Fabric-E"`, `member_of_groups: ["tenants"]`), VRF `purple-prod`, and segments `purple-web`/`purple-app` (routed) plus `purple-l2` (L2-only). **Without this, no SONiC leaf renders any overlay config** — scope it to Fabric-E only; adding tenants to B/C would change their configs and violate FR-010 (spec FR-011)

### Validation for User Story 1

Per [quickstart.md](./quickstart.md).

- [x] T018 [US1] Run `inv lint` and `inv test`; both must pass before loading — `inv lint` clean (98 files); `inv test` unit suite 245 passed/0 failed; the 25 integration-test errors are pre-existing (`Docker image 'opsmill/infrahub-solution-ai-dc:1.11.0b0' is missing` — no Docker daemon in this sandbox, unrelated to this feature's changes)
- [ ] T019 [US1] Fresh load: `inv destroy && inv start && inv load`, then confirm the SONiC manufacturer, all four device types (with their chipset comments), the `sonic_devices` group (parent `devices`), eight object templates with interfaces expanded to `Eth1/N` alias names (65 on every spine/super-spine template regardless of generation, 55 on each leaf template), and the `Purple` tenant with its VRF and three segments (quickstart Scenario 1)
- [ ] T020 [US1] Generate Fabric-E and verify 23 devices (4 super-spines, 8 spines, 11 leaves), every one a member of `devices` **and** `sonic_devices` and no other vendor group, Pod-E1's super-spines built from `SONiC-T6`, Pod-E2's spines from `SONiC-T4`, Pod-E3's spines from `SONiC-T5` (checked via `device_type`, not hostname), and leaves carrying `Eth1/1`–`Eth1/48`, `Eth1/49`–`Eth1/54`, `Loopback0` and a runtime `Loopback1` of role `vtep` (quickstart Scenario 2)
- [ ] T021 [US1] Verify cabling: leaf uplinks (`Eth1/49`+) pair to distinct spine downlinks (`Eth1/1`–`Eth1/32`) in numerically correct order, no access port is ever cabled to a spine, no port appears twice, 4 of 6 uplinks cabled per leaf (quickstart Scenario 3)
- [ ] T022 [US1] Verify every device across all five fabrics has exactly one `Startup configuration` artifact — none with zero, none with two (quickstart Scenario 4, SC-003)
- [ ] T023 [US1] Inspect a Fabric-E leaf config: every `config` CLI line is a complete standalone command, `config vlan add`/`config vxlan map add`/`config interface ip add Vlan<id>`/`config interface vrf bind`/an FRR `vrf .../vni .../exit-vrf` block present for gateway-bearing segments, `vtep1`'s source address is the `vtep`-role interface (never the loopback), uncabled uplinks still get description+shutdown, and the L2-only segment `purple-l2` renders `config vlan add` + `config vxlan map add` with **no** `config interface ip add Vlan<id>` and **no** `config interface vrf bind` line (quickstart Scenario 5, contract A1/A2/A4/A5/A7)
- [ ] T024 [US1] Inspect a spine from Pod-E2 (`SONiC-T4`), a spine from Pod-E3 (`SONiC-T5`), and the super-spine from Pod-E1 (`SONiC-T6`): FRR `router bgp`/`address-family l2vpn evpn` present, **no** `config vlan`/`config vxlan`/`vrf ... vni ...` block anywhere, `route-reflector-client` only on reflecting tiers, and **identical structure across all three chipset generations** — any difference beyond hostname/addressing is a bug (quickstart Scenario 6, contract A3/A6)
- [ ] T025 [US1] Verify a zero-line diff on rendered configs for one Cisco, one Arista, one Dell and one Juniper device (quickstart Scenario 7, FR-010)

**Checkpoint**: US1 is complete and independently demonstrable — this is the MVP.

---

## Phase 4: Polish & Cross-Cutting Concerns

**Purpose**: Keep the agent-facing and human-facing documentation truthful, and close the success criteria.

- [x] T026 `CONTEXT.md` — extend the Vendor group definition and add a Flagged-ambiguities entry recording that Manufacturer/Device Type name whatever is config-relevant (OS, chipset generation), not necessarily a legal hardware maker or specific ODM box (**already applied**; verify both edits are present)
- [ ] T027 [P] Update the vendor list in the templates bullet at `AGENTS.md` (`startup_config_{cisco,arista,dell,juniper}.j2` → include `sonic`)
- [ ] T028 [P] Add this feature to the active-features list in `CLAUDE.md`
- [ ] T029 [P] Update vendor mentions in `README.md`
- [ ] T030 [P] Update vendor lists in `docs/docs/solution-ai-dc/` — `multivendor-config.mdx` is the dedicated page (group table, transform/artifact table, demo-data table, and the `SUPPORTED_VENDORS` prose), plus `overview.mdx`, `installation-setup.mdx`, `demo-guide.mdx`, `evpn-vxlan-overlay.mdx`
- [ ] T031 [P] Add `SONiC`, `Tomahawk`, `Trident`, `Broadcom`, `FRR`, `vtysh`, `NVO` to `.vale/styles/spelling-exceptions.txt` (`Juniper`/`Junos` already present)
- [ ] T032 Run the documentation linter over the edited `docs/` pages and confirm it passes. `inv lint` is yamllint + ruff + mypy only and does **not** cover Vale, so nothing else verifies T031 — run Vale directly or via the CI docs job
- [ ] T033 Verify SC-002: `git diff --stat main -- schemas/ generators/` must be **empty**. A non-empty diff means the multivendor abstraction leaked and should be recorded as a finding (quickstart Scenario 9)
- [ ] T034 Verify the day-two overlay path reaches SONiC leaves: add a fourth segment to the `Purple` tenant's `purple-prod` VRF, re-run the overlay generator, and confirm carrying leaves pick it up while SONiC spine/super-spine configs stay byte-identical across all three chipset generations (quickstart Scenario 8, contract A8)
- [ ] T035 Verify SC-004: walk Fabric-E design object → generated switches and cabling → rendered SONiC configuration, without editing code and running nothing beyond `inv load` plus the generator pipeline (quickstart Scenario 10)
- [ ] T036 **SC-001 review gate**: have a reviewer with production SONiC/FRR experience review one leaf config and one spine/super-spine config (ideally one from `SONiC-T4` and the `SONiC-T6` super-spine, to sanity-check the newest, least-proven generation too). Brief them with the scoped mandate — the `config`-CLI/FRR split, correct verb usage in each section, EVPN/VXLAN structure only; management addressing, MTU and AAA/NTP/syslog are repo-wide simplifications and out of scope. Target: zero blocking structural findings

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Setup)** → no dependencies
- **Phase 2 (Foundational)** → depends on Phase 1. **Blocks all of Phase 3.**
- **Phase 3 (US1)** → depends on Phase 2 complete
- **Phase 4 (Polish)** → doc tasks (T027-T032) can start any time; T033-T036 require Phase 3 complete; T026 is already done

### Critical ordering constraints

- **T002 before T003** — the test only passes once the vendor is in the allow-list.
- **T005/T006 before T007** — the device templates reference device types by human-friendly ID
  (`["SONiC", "SONiC-T4"]` etc.), which must resolve at load time.
- **T007 before T008** — the new test asserts against the templates T007 creates.
- **T007 before T015/T016** — the fabric and racks reference the object templates by name.
- **T015 before T017** — the `Purple` tenant references `fabric: "Fabric-E"`, which must exist.
- **T004 before T014** — the artifact definition targets `sonic_devices`; if the group name does not match
  `f"{manufacturer.lower()}_devices"` exactly, artifact targeting silently matches **nothing** rather than
  erroring.
- **T014 before T022** — no registration, no artifacts.
- **T017 before T023** — no tenant, no overlay stanzas to inspect. This is the dependency that makes the
  leaf-config check satisfiable at all.
- **T019 before T020 before T021/T022** — load, then generate, then inspect.
- **T031 before T032** — the linter check only means something once the exceptions are added.

### Within-file serialization (no [P])

- **T009 → T013** all edit `transforms/templates/startup_config_sonic.j2`. Strictly sequential.
- **T014** is the only `.infrahub.yml` edit (two additive blocks in one task).

### Parallel Opportunities

- **Phase 2**: T004, T005, T006, T007 are four different object files — fully parallel after T002/T003 (T008
  should follow T007, not run alongside it, since it tests what T007 writes).
- **Phase 3**: T015, T016 and T017 are three different object files, parallel with each other (subject to
  T015 → T017) and with the template chain T009-T013.
- **Phase 4**: T027-T031 are five different documentation files — fully parallel.

---

## Parallel Example: Phase 2

```bash
# After T002 (allow-list) and T003 (test fix), the four data files are independent:
T004  objects/01_groups.yml          # sonic_devices group
T005  objects/02_manufacturer.yml    # SONiC
T006  objects/03_device_type.yml     # SONiC-T4, SONiC-T5, SONiC-T6, SONiC-TD4
T007  objects/06_device_template.yml # eight device templates
```

## Parallel Example: User Story 1

```bash
# The template chain is sequential, but the demo data is not — run alongside it:
T015  objects/10_fabric.yml   # Fabric-E + Pod-E1(T6)/E2(T4)/E3(T5)
T016  objects/11_rack.yml     # 8 Fabric-E racks, all on SONiC-TD4
T017  objects/12_overlay.yml  # Purple tenant (after T015 — references Fabric-E)
```

---

## Implementation Strategy

### MVP First (User Story 1)

Phases 1-3 are the MVP and the whole feature — there is only one user story. Completing Phase 3 delivers the
full evaluator experience: recognisable SONiC hardware spanning three real chipset generations, alias-mode
interface names, correct cabling, and a rendered SONiC startup configuration carrying real tenant overlay on
every SONiC leaf.

### Incremental Delivery

1. **Phase 2 alone** is loadable and verifiable — the SONiC manufacturer, all four device types, the group
   and all eight templates exist, and `inv load` succeeds — but produces no devices and no configs. Not
   demonstrable on its own, which is exactly why the spec keeps the demo fabric inside US1.
2. **Phase 3 through T017** makes the fabric generate with a real tenant, across three chipset generations.
   **T018-T025** prove it.
3. **Phase 4** closes the documentation and the four success criteria that need a human or a diff.

### Suggested checkpoints

- After T008: `inv lint` and `uv run pytest tests/unit/test_vendors.py tests/unit/test_sonic_device_templates.py` green.
- After T017: `inv destroy && inv start && inv load` succeeds with no loader errors.
- After T025: the feature is functionally complete; only docs and the review gate remain.

---

## Notes

- **The riskiest tasks are T011-T012.** Unlike the flat single-syntax templates, SONiC genuinely mixes two
  command dialects in one artifact — a `config` CLI verb landing in the FRR section (or vice versa) is this
  feature's most likely defect, with no automated test behind it (research.md D5, D6).
- **T003 and T017 are both easy to skip.** T003 is not fatal (the happy-path parametrize just stays
  incomplete). T017 fails silently — everything loads and generates, every other check passes, and the leaf
  config simply has no overlay in it.
- **T007 and T008 are a matched pair.** Eight templates that are meant to be near-identical copies are exactly
  the shape of change most likely to suffer a silent copy-paste error (a T5 template pointing at
  `SONiC-T4`'s device type). T008 exists specifically to catch that — do not treat it as optional polish.
- **The computed interface `index` attribute renders `000` for SONiC's `Eth1/N` alias names**, the same
  pre-existing, vendor-wide, out-of-scope behaviour Cisco/Dell/Juniper already have. Do not "fix" it here.
- **Fabric-E needs no manual IPAM or ASN entries.** `generate_fabric.py`'s `allocate_resource_pools` carves a
  per-fabric `/16` and allocates the overlay ASN from a pool, exactly as it did for Fabric-D — unaffected by
  which chipset generation each pod's templates reference. The OverlayGenerator likewise allocates every VNI,
  VLAN, route target, subnet and gateway for the `Purple` tenant — none are declared in the object data.
- **`SONiC-T6` is the newest, least field-proven generation modeled here** (research.md D7). T036 deliberately
  includes it in the review gate rather than only reviewing the most established generation (`SONiC-T4`).
