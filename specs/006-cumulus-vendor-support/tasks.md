---

description: "Task list for NVIDIA Cumulus Linux Vendor Support"
---

# Tasks: NVIDIA Cumulus Linux Vendor Support

**Input**: Design documents from `/specs/006-cumulus-vendor-support/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md

**Tests**: Two unit-test files are touched. `tests/unit/test_vendors.py` needs a Cumulus happy-path case added
(not fatal if skipped — the negative-path fixture is unaffected). `tests/unit/test_cumulus_device_templates.py`
is **new** and **not optional**: it guards the eight near-identical device templates against a
copy-paste/wiring error (research.md D10, applying SONiC's D12 precedent from the start). No
configuration-template test is generated: automated template validation was explicitly declined (research.md
D6); correctness is established by human review (SC-001) and the `quickstart.md` scenarios.

**Organization**: The spec has a single user story (US1). Phase 2 holds the vendor plumbing — including all
four device types and all eight device templates — that must exist before anything can be generated; Phase 3
is US1: the Cumulus template (ifupdown2 stanzas + FRR, one artifact), its registration, the
three-Spectrum-generation demo fabric and its tenant, and the validation that proves the evaluator experience
works.

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

- [ ] T001 Sync dependencies and confirm the working branch: run `uv sync --all-groups --all-extras` from the repo root, on branch `006-cumulus-vendor-support`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Vendor plumbing and all four Spectrum-generation device-type/template definitions. Nothing in
US1 can be generated or rendered until these exist. Per
[contracts/cumulus-registration.md](./contracts/cumulus-registration.md) and [data-model.md](./data-model.md).

- [ ] T002 Add `"cumulus"` to `SUPPORTED_VENDORS` in `src/infrahub_solution_ai_dc/vendors.py` — the entire Python delta for this feature
- [ ] T003 Add `("Cumulus", "cumulus_devices")` to the happy-path parametrize in `tests/unit/test_vendors.py`; confirm the existing negative-path fixture (a still-unsupported manufacturer) is unaffected — no edit needed there since only `"cumulus"` is being added
- [ ] T004 [P] Add the `cumulus_devices` group with `parent: devices` in `objects/01_groups.yml`
- [ ] T005 [P] Add `- name: Cumulus` in `objects/02_manufacturer.yml`
- [ ] T006 [P] Add four device types in `objects/03_device_type.yml` — `Cumulus-SPECTRUM2`, `Cumulus-SPECTRUM3`, `Cumulus-SPECTRUM4`, `Cumulus-SPECTRUM2-TOR`, all `manufacturer: ["Cumulus"]` — with the inline ASIC/capacity comment for each from data-model.md §3 (research.md D7)
- [ ] T007 [P] Add eight `TemplateNetworkDevice` entries in `objects/06_device_template.yml` — `cumulus-spectrum2-super-spine-switch`, `cumulus-spectrum2-spine-switch`, `cumulus-spectrum3-super-spine-switch`, `cumulus-spectrum3-spine-switch`, `cumulus-spectrum4-super-spine-switch`, `cumulus-spectrum4-spine-switch`, `cumulus-spectrum2-tor-leaf-switch-compute`, `cumulus-spectrum2-tor-leaf-switch-storage` — with the interface/profile split in data-model.md §4 (`swp[1-32]`/`swp[33-64]` split for spines, `swp[1-64]` for super-spines, `swp[1-48]`/`swp[49-54]` for leaves), `expand_range: true` on both levels, and exactly one `Loopback0` (role `loopback`) each. The three spine templates and three super-spine templates are byte-identical except `template_name` and `device_type` — copy-paste-rename, not redesign (data-model.md §4)
- [ ] T008 Create `tests/unit/test_cumulus_device_templates.py` per research.md D10 (structured like `tests/unit/test_sonic_device_templates.py`): for all eight templates from T007, assert `device_type` matches the intended ASIC-generation/role pairing, assert `infrahub_sdk.spec.range_expansion.range_expansion` on each declared interface pattern expands to the expected count and first/last name (65 total interfaces for every spine/super-spine template, 55 for both leaf templates), assert each template's top-level `role` matches its intended tier, and assert `interfaces.parameters.expand_range` is `true` on every template

**Checkpoint**: `uv run pytest tests/unit/test_vendors.py tests/unit/test_cumulus_device_templates.py` is green and `inv lint` passes.

---

## Phase 3: User Story 1 - A Cumulus Linux evaluator sees their hardware and their config (Priority: P1) 🎯 MVP

**Goal**: A Cumulus-shop evaluator can trace design intent → generated Cumulus switches (spanning three
Spectrum generations) and cabling → a rendered Cumulus Linux startup configuration, using hardware and syntax
they recognise.

**Independent Test**: Load the solution, generate Fabric-F, and open the `Startup configuration` artifact on
a Fabric-F leaf and on a spine from each of the three pods (Spectrum-2/3/4). The leaf shows EVPN/VXLAN with
tenant segments; every spine/super-spine shows the control plane with no tenant overlay, identically
structured regardless of Spectrum generation.

### Implementation for User Story 1

The template tasks all edit `transforms/templates/startup_config_cumulus.j2` and are therefore **strictly
sequential** — no `[P]`. Build the file section by section against
[contracts/cumulus-config-contract.md](./contracts/cumulus-config-contract.md).

- [ ] T009 [US1] Create `transforms/templates/startup_config_cumulus.j2` with the preamble — copy the `device`/`fabric`/`overlay_asn` fallback, the `vns` VRF de-dup namespace, `is_rr`, and the `evpn_sessions`/`ipv4_sessions` address-family split from `startup_config_sonic.j2` (all vendor-neutral Jinja preamble logic, not SONiC syntax) — then emit the always-present `/etc/network/interfaces` section: for every `super_spine`/`spine`/`leaf`/`server`-role interface (unfiltered loop, excluding `loopback`/`vtep` roles), an `auto <name>`/`iface <name>` stanza with `alias <description>` and `address <ip CIDR>` when active, or an `iface <name>` stanza (no `auto` line) with `alias`/`link-down yes` when `status == "inactive"` (uncabled ports still get a stanza per contract A7) — plus the `lo` stanza with `address <loopback_ip>/32`
- [ ] T010 [US1] Add the FRR EVPN control-plane section to `transforms/templates/startup_config_cumulus.j2`, gated on `overlay_asn is not none`: `router bgp <asn>` / `bgp router-id` / `no bgp default ipv4-unicast` / one `neighbor ... remote-as ...` + `update-source lo` + `send-community extended` per EVPN session (sorted by peer hostname, contract A8) / `neighbor ... remote-as ...` per `ipv4_sessions` entry / `address-family l2vpn evpn` with `neighbor ... activate`, `neighbor ... route-reflector-client` only when `is_rr` and the session has `rr_client` (contract A6), and `advertise-all-vni` / `address-family ipv4 unicast` (only if `ipv4_sessions` non-empty) with `neighbor ... activate`
- [ ] T011 [US1] Add the leaf-only tenant overlay's `/etc/network/interfaces` section, gated on `device.segments.edges`: `auto bridge`/`iface bridge` with `bridge-vlan-aware yes`, `bridge-ports` listing every segment's `vni<l2vni>` interface, and `bridge-vids` listing every segment's `vlan_id`; one `auto vni<l2vni>`/`iface vni<l2vni>` stanza per segment (gateway or not) with `vxlan-id <l2vni>`, `vxlan-local-tunnelip <vtep-role interface's address>` (loud `# ERROR: ...` comment fallback if none found, contract A4/D13-equivalent), and `bridge-access <vlan_id>`; one `auto vlan<vlan_id>`/`iface vlan<vlan_id>` stanza **only** for gateway-bearing segments with `address <gateway CIDR>`, `vlan-raw-device bridge`, `vlan-id <vlan_id>`, `vrf <vrf name>` (contract A5 — the L2-only segment gets only the `vni<l2vni>` stanza and a `bridge-vids` entry, never a `vlan<vlan_id>` stanza)
- [ ] T012 [US1] Add the leaf-only tenant overlay's FRR section to `transforms/templates/startup_config_cumulus.j2`, with its **own** `overlay_asn is not none` guard (not relying on the outer one — SONiC D13 defect 3 precedent): per-segment `vni <l2vni> / rd <loopback_ip>:<vlan_id> / route-target both <route_target>` inside `address-family l2vpn evpn`, plus a top-level `vrf <name> / vni <l3vni> / exit-vrf` block per materialised VRF (contract A2)
- [ ] T013 [US1] Add a one-line comment banner at the top of each syntax section in `transforms/templates/startup_config_cumulus.j2` (`# --- /etc/network/interfaces (ifupdown2) ... ---` / `! --- FRR routing config ... ---`) naming how that section is actually applied on a real device, matching the SONiC template's own banner convention (critique P2 precedent)
- [ ] T014 [US1] Register the vendor in `.infrahub.yml`: add the `cumulus_device_startup_config` entry to `jinja2_transforms` (after the `sonic_device_startup_config` entry) and the `cumulus_startup_configuration` entry to `artifact_definitions` (after `sonic_startup_configuration`), targeting `cumulus_devices`, reusing the existing `network_device_startup_config` query, and keeping `artifact_name: "Startup configuration"` identical to the other five
- [ ] T015 [P] [US1] Add `Fabric-F` (index 6, 4 super-spines, `super_spine_switch_template: cumulus-spectrum4-super-spine-switch`) with `Pod-F1` (`role: "fabric"`, no spine template), `Pod-F2` (`spine_switch_template: cumulus-spectrum2-spine-switch`) and `Pod-F3` (`spine_switch_template: cumulus-spectrum3-spine-switch`) in `objects/10_fabric.yml`, mirroring Fabric-E's topology (data-model.md §5 — three Spectrum generations, one per pod, research.md D8)
- [ ] T016 [P] [US1] Add the eight Fabric-F racks in `objects/11_rack.yml` per the table in data-model.md §6, mirroring the Fabric-E block — **including its two `rack_type`/template mismatches** — all using the single `cumulus-spectrum2-tor-leaf-switch-{compute,storage}` templates regardless of which pod (and therefore which spine generation) they attach to
- [ ] T017 [P] [US1] Add the `Amber` overlay tenant to `objects/12_overlay.yml` per data-model.md §7 — tenant `Amber` (`fabric: "Fabric-F"`, `member_of_groups: ["tenants"]`), VRF `amber-prod`, and segments `amber-web`/`amber-app` (routed) plus `amber-l2` (L2-only). **Without this, no Cumulus leaf renders any overlay config** — scope it to Fabric-F only; adding tenants to other fabrics would change their configs and violate FR-010 (spec FR-011)

### Validation for User Story 1

Per [quickstart.md](./quickstart.md).

- [ ] T018 [US1] Run `inv lint` and `inv test`; both must pass before loading
- [ ] T019 [US1] Fresh load: `inv destroy && inv start && inv load`, then confirm the Cumulus manufacturer, all four device types (with their ASIC comments), the `cumulus_devices` group (parent `devices`), eight object templates with interfaces expanded to `swpN` names (65 on every spine/super-spine template regardless of generation, 55 on each leaf template), and the `Amber` tenant with its VRF and three segments (quickstart Scenario 1)
- [ ] T020 [US1] Generate Fabric-F and verify 23 devices (4 super-spines, 8 spines, 11 leaves), every one a member of `devices` **and** `cumulus_devices` and no other vendor group, Pod-F1's super-spines built from `Cumulus-SPECTRUM4`, Pod-F2's spines from `Cumulus-SPECTRUM2`, Pod-F3's spines from `Cumulus-SPECTRUM3` (checked via `device_type`, not hostname), and leaves carrying `swp1`–`swp48`, `swp49`–`swp54`, `Loopback0` and a runtime `Loopback1` of role `vtep` (quickstart Scenario 2)
- [ ] T021 [US1] Verify cabling: leaf uplinks (`swp49`+) pair to distinct spine downlinks (`swp1`–`swp32`) in numerically correct order, no access port is ever cabled to a spine, no port appears twice, 4 of 6 uplinks cabled per leaf (quickstart Scenario 3)
- [ ] T022 [US1] Verify every device across all six fabrics has exactly one `Startup configuration` artifact — none with zero, none with two (quickstart Scenario 4, SC-003)
- [ ] T023 [US1] Inspect a Fabric-F leaf config: every `/etc/network/interfaces` stanza is complete (A1), `bridge`/`vni<l2vni>`/`vlan<vlan_id>` stanzas and an FRR `vrf .../vni .../exit-vrf` block present for gateway-bearing segments (A2), `vxlan-local-tunnelip` uses the `vtep`-role interface (never the loopback) (A4), uncabled uplinks still get an `iface` stanza with `link-down yes` (A7), and the L2-only segment `amber-l2` renders a `vni<l2vni>` stanza plus a `bridge-vids` entry with **no** `vlan<vlan_id>` stanza (quickstart Scenario 5, contract A5)
- [ ] T024 [US1] Inspect a spine from Pod-F2 (`Cumulus-SPECTRUM2`), a spine from Pod-F3 (`Cumulus-SPECTRUM3`), and the super-spine from Pod-F1 (`Cumulus-SPECTRUM4`): FRR `router bgp`/`address-family l2vpn evpn` present, **no** `bridge`/`vni<N>`/`vrf ... vni ...` block anywhere, `route-reflector-client` only on reflecting tiers, and **identical structure across all three Spectrum generations** — any difference beyond hostname/addressing is a bug (quickstart Scenario 6, contract A3/A6)
- [ ] T025 [US1] Verify a zero-line diff on rendered configs for one Cisco, one Arista, one Dell, one Juniper and one SONiC device (quickstart Scenario 7, FR-010)

**Checkpoint**: US1 is complete and independently demonstrable — this is the MVP.

---

## Phase 4: Polish & Cross-Cutting Concerns

**Purpose**: Keep the agent-facing and human-facing documentation truthful, and close the success criteria.

- [ ] T026 `CONTEXT.md` — extend the Vendor group definition / Flagged-ambiguities entry to note Cumulus alongside SONiC as another manufacturer named for config dialect (OS + Spectrum ASIC generation), not a legal hardware maker distinction, consistent with the existing SONiC entry
- [ ] T027 [P] Update the vendor list in the templates bullet at `AGENTS.md` (`startup_config_{cisco,arista,dell,juniper,sonic}.j2` → include `cumulus`)
- [ ] T028 [P] Add this feature to the active-features list in `CLAUDE.md`
- [ ] T029 [P] Update vendor mentions in `README.md`
- [ ] T030 [P] Update vendor lists in `docs/docs/solution-ai-dc/` — `multivendor-config.mdx` is the dedicated page (group table, transform/artifact table, demo-data table, and the `SUPPORTED_VENDORS` prose), plus `overview.mdx`, `installation-setup.mdx`, `demo-guide.mdx`, `evpn-vxlan-overlay.mdx`
- [ ] T031 [P] Add `Cumulus`, `Spectrum`, `ifupdown2`, `vxlan`-related terms not already present to `.vale/styles/spelling-exceptions.txt` (`FRR`/`vtysh` already present from SONiC)
- [ ] T032 Run the documentation linter over the edited `docs/` pages and confirm it passes. `inv lint` is yamllint + ruff + mypy only and does **not** cover Vale, so nothing else verifies T031 — run Vale directly or via the CI docs job
- [ ] T033 Verify SC-002: `git diff --stat main -- schemas/ generators/` must be **empty**. A non-empty diff means the multivendor abstraction leaked and should be recorded as a finding (quickstart Scenario 9)
- [ ] T034 Verify the day-two overlay path reaches Cumulus leaves: add a fourth segment to the `Amber` tenant's `amber-prod` VRF, re-run the overlay generator, and confirm carrying leaves pick it up while Cumulus spine/super-spine configs stay byte-identical across all three Spectrum generations (quickstart Scenario 8, contract A8)
- [ ] T035 Verify SC-004: walk Fabric-F design object → generated switches and cabling → rendered Cumulus configuration, without editing code and running nothing beyond `inv load` plus the generator pipeline (quickstart Scenario 10)
- [ ] T036 **SC-001 review gate**: have a reviewer with production Cumulus Linux/FRR experience review one leaf config and one spine/super-spine config (ideally one from `Cumulus-SPECTRUM2` and the `Cumulus-SPECTRUM4` super-spine, to sanity-check the newest, least-proven generation too). Brief them with the scoped mandate — the `/etc/network/interfaces`/FRR split, correct stanza attribution in each section, EVPN/VXLAN structure only; management addressing, MTU and AAA/NTP/syslog are repo-wide simplifications and out of scope. Also ask them to confirm the two hedged mechanics from critique-20260902-154300 (`link-down yes`/omit-`auto` for admin-down ports, and the deliberate STP-guard omission). Target: zero blocking structural findings

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
  (`["Cumulus", "Cumulus-SPECTRUM2"]` etc.), which must resolve at load time.
- **T007 before T008** — the new test asserts against the templates T007 creates.
- **T007 before T015/T016** — the fabric and racks reference the object templates by name.
- **T015 before T017** — the `Amber` tenant references `fabric: "Fabric-F"`, which must exist.
- **T004 before T014** — the artifact definition targets `cumulus_devices`; if the group name does not match
  `f"{manufacturer.lower()}_devices"` exactly, artifact targeting silently matches **nothing** rather than
  erroring.
- **T014 before T022** — no registration, no artifacts.
- **T017 before T023** — no tenant, no overlay stanzas to inspect. This is the dependency that makes the
  leaf-config check satisfiable at all.
- **T019 before T020 before T021/T022** — load, then generate, then inspect.
- **T031 before T032** — the linter check only means something once the exceptions are added.

### Within-file serialization (no [P])

- **T009 → T013** all edit `transforms/templates/startup_config_cumulus.j2`. Strictly sequential.
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
T004  objects/01_groups.yml          # cumulus_devices group
T005  objects/02_manufacturer.yml    # Cumulus
T006  objects/03_device_type.yml     # Cumulus-SPECTRUM2, -SPECTRUM3, -SPECTRUM4, -SPECTRUM2-TOR
T007  objects/06_device_template.yml # eight device templates
```

## Parallel Example: User Story 1

```bash
# The template chain is sequential, but the demo data is not — run alongside it:
T015  objects/10_fabric.yml   # Fabric-F + Pod-F1(SPECTRUM4)/F2(SPECTRUM2)/F3(SPECTRUM3)
T016  objects/11_rack.yml     # 8 Fabric-F racks, all on Cumulus-SPECTRUM2-TOR
T017  objects/12_overlay.yml  # Amber tenant (after T015 — references Fabric-F)
```

---

## Implementation Strategy

### MVP First (User Story 1)

Phases 1-3 are the MVP and the whole feature — there is only one user story. Completing Phase 3 delivers the
full evaluator experience: recognisable Cumulus Linux hardware spanning three real Spectrum ASIC generations,
`swp`-convention interface names, correct cabling, and a rendered Cumulus Linux startup configuration carrying
real tenant overlay on every Cumulus leaf.

### Incremental Delivery

1. **Phase 2 alone** is loadable and verifiable — the Cumulus manufacturer, all four device types, the group
   and all eight templates exist, and `inv load` succeeds — but produces no devices and no configs. Not
   demonstrable on its own, which is exactly why the spec keeps the demo fabric inside US1.
2. **Phase 3 through T017** makes the fabric generate with a real tenant, across three Spectrum generations.
   **T018-T025** prove it.
3. **Phase 4** closes the documentation and the four success criteria that need a human or a diff.

### Suggested checkpoints

- After T008: `inv lint` and `uv run pytest tests/unit/test_vendors.py tests/unit/test_cumulus_device_templates.py` green.
- After T017: `inv destroy && inv start && inv load` succeeds with no loader errors.
- After T025: the feature is functionally complete; only docs and the review gate remain.

---

## Notes

- **The riskiest tasks are T009 and T011.** Unlike SONiC's wrong-dialect-verb risk, Cumulus's real risk is a
  `/etc/network/interfaces` attribute line drifting outside its owning stanza (research.md D5) — a third
  distinct structural shape with no automated test behind it (research.md D6).
- **T003 and T017 are both easy to skip.** T003 is not fatal (the happy-path parametrize just stays
  incomplete). T017 fails silently — everything loads and generates, every other check passes, and the leaf
  config simply has no overlay in it.
- **T007 and T008 are a matched pair.** Eight templates that are meant to be near-identical copies are exactly
  the shape of change most likely to suffer a silent copy-paste error (a Spectrum-3 template pointing at
  `Cumulus-SPECTRUM2`'s device type). T008 exists specifically to catch that — do not treat it as optional
  polish.
- **The computed interface `index` attribute is expected to render the real port number for `swpN` names**
  (unlike SONiC/Cisco/Dell/Juniper's `000` quirk) — confirm during T019/T020 rather than assume (research.md
  D3).
- **Fabric-F needs no manual IPAM or ASN entries.** `generate_fabric.py`'s `allocate_resource_pools` carves a
  per-fabric `/16` and allocates the overlay ASN from a pool, exactly as it did for Fabric-E — unaffected by
  which Spectrum generation each pod's templates reference. The OverlayGenerator likewise allocates every VNI,
  VLAN, route target, subnet and gateway for the `Amber` tenant — none are declared in the object data.
- **`Cumulus-SPECTRUM4` is the newest, least field-proven generation modeled here** (research.md D7). T036
  deliberately includes it in the review gate rather than only reviewing the most established generation
  (`Cumulus-SPECTRUM2`).
- **Two mechanics carry an explicit confirm-at-review hedge** (critique-20260902-154300, E1/E2): the
  `link-down yes`/omit-`auto` admin-down convention, and the deliberate omission of STP guard attributes on
  `vni<N>` stanzas. T036 names both explicitly so the reviewer knows to check them.
