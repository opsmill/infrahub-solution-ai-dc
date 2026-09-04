# Feature Specification: SONiC Vendor Support

**Feature Branch**: `005-sonic-vendor-support`

**Created**: 2026-08-27

**Status**: Draft

**Input**: User description: "Add SONiC as a fifth supported network device vendor, following the exact pattern established by 002-multivendor-config and exercised end-to-end by 003-juniper-junos-support. Scope: add SONiC to the supported-vendors list, create a new startup-config template for SONiC's device syntax, register a SONiC config transform and artifact definition targeting a new sonic_devices group, add SONiC manufacturer/device-type/device-template object data, and add a demo fabric/rack so the new vendor is visible and inspectable end-to-end. No schema changes and no generator changes should be needed -- if either turns out to be necessary, that's a finding to flag, not something to silently do."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - A SONiC evaluator sees their hardware and their config (Priority: P1)

A network engineer from an organisation standardised on open networking / disaggregated NOS deployments is shown the AI/DC reference solution by a solutions engineer. Today they see four data-center fabrics built from Cisco, Arista, Dell and Juniper hardware, and generated configurations in four vendor dialects — none of which resembles the open-source, Linux-based operating system their own fleet runs. They have no way to assess whether the solution understands their environment.

After this feature, the demo includes a fifth fabric built entirely from SONiC-class hardware. The evaluator can trace the same path they saw for the other vendors — a fabric described as design intent, expanded into switches, interfaces and cabling, and rendered as a device startup configuration — except the switches are open-networking hardware they recognise, the interface names follow SONiC conventions, and the configuration is SONiC's.

**Why this priority**: This is the only journey. The feature exists to let a SONiC-shop evaluator recognise their own environment; anything that stops short of a readable SONiC configuration on recognisable hardware delivers nothing to that person.

The demo data is inside this slice rather than being a follow-on. A vendor capability with no fabric using it is invisible to the evaluator and cannot be inspected — the demo fabric is both the deliverable and the means of verifying it.

**Independent Test**: Load the reference solution, run generation for the SONiC fabric, and open the startup-configuration artifact on a SONiC leaf switch and on a SONiC spine switch. Delivers the complete evaluator experience with no other work required.

**Acceptance Scenarios**:

1. **Given** the reference solution is loaded and generation has run for the SONiC fabric, **When** an evaluator opens the startup-configuration artifact on a SONiC leaf switch, **Then** it renders SONiC configuration containing the EVPN control plane, the VXLAN tunnel endpoint sourced from the leaf's tunnel loopback, one VLAN-to-VNI mapping per tenant segment, and a VRF binding for the tenant.

2. **Given** the same loaded solution, **When** an evaluator opens the startup-configuration artifact on a SONiC spine or super-spine switch, **Then** it contains the EVPN control-plane configuration but **no** tenant VLAN-to-VNI mappings, no tunnel-endpoint configuration, and no tenant VRF bindings — because spines and super-spines are never tunnel endpoints.

3. **Given** the SONiC fabric has been generated, **When** an operator inspects any generated SONiC switch, **Then** it carries SONiC-convention interface names and belongs to both the general device grouping and the SONiC vendor grouping.

4. **Given** the SONiC fabric has been generated, **When** an operator inspects the cabling between a SONiC rack and its pod, **Then** each leaf uplink port is cabled to a distinct spine downlink port, with no port paired twice and none left unintentionally unpaired.

### Edge Cases

- **SONiC configuration is split across two distinct syntaxes.** Interface, VLAN and VXLAN-tunnel provisioning follow one (Linux-style) convention, while the EVPN/BGP control plane follows a separate routing-daemon syntax. Unlike the three flat vendor dialects (a scoping mistake there produces one wrong line) and similar in kind to Junos's hierarchy risk, mixing the two SONiC syntaxes or emitting one inside the other was this feature's most likely failure mode — resolved by rendering each syntax into its own artifact (`Startup configuration` / `FRR configuration`, FR-006) rather than relying on in-file section discipline.

- **Interface naming must use SONiC's real front-panel (alias) convention** (`Eth1/N`, sequential per port) rather than the alternative lane-indexed default-mode naming SONiC also supports (`EthernetN`, stepping by lane count). Cabling and rendering must use the correct SONiC-convention name per port.

- **A tenant segment may have no anycast gateway.** A segment without a gateway is L2-only. Its VLAN-to-VNI mapping must still be rendered, but no routed (VRF-bound) interface may be emitted for it.

- **Not every uplink port is cabled.** If the chosen SONiC leaf model has more uplink ports than there are spine switches in a pod, surplus uplinks must render as present-but-disabled interfaces, consistent with how uncabled access ports already appear for every vendor.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST recognise SONiC as a supported vendor and place every device running it into a dedicated SONiC vendor grouping.
- **FR-002**: System MUST reject devices whose manufacturer/vendor is not supported, naming the offending device, and MUST continue to do so for vendors other than SONiC.
- **FR-003**: Users MUST be able to designate a fabric, pod or rack as SONiC-built, and have generation produce SONiC switches carrying SONiC-convention interface names.
- **FR-004**: System MUST place every generated SONiC switch into both the general device grouping and the SONiC vendor grouping.
- **FR-005**: System MUST cable SONiC leaf uplinks to their pod's spine downlinks correctly, using SONiC's own interface-naming convention.
- **FR-006**: System MUST render exactly two startup-configuration artifacts for every SONiC switch — a `Startup configuration` artifact (SONiC `config` CLI: interfaces, VLAN/VXLAN) and an `FRR configuration` artifact (BGP underlay + EVPN) — not zero of either, not more than one of either. This is a deliberate exception to the "exactly one" rule the other four vendors follow (FR-010, SC-003): SONiC genuinely applies these two dialects through separate mechanisms (`config`/`config_db.json` vs. `vtysh`/`frr.conf`), so splitting them into separate artifacts removes the risk of one dialect's command landing in the other's section, at the cost of no longer being a single "show running-config" file.
- **FR-007**: System MUST render the tenant overlay — VLAN-to-VNI mappings, tunnel endpoint, routed interfaces and VRF bindings — only on leaf switches, and MUST NOT render any of it on spines or super-spines.
- **FR-008**: System MUST render the EVPN control plane on SONiC switches of every tier, reflecting each switch's stored route-reflector role.
- **FR-009**: The reference solution MUST ship a SONiC fabric of the same topology as the existing fabrics, so an evaluator sees a complete SONiC environment rather than an isolated switch.
- **FR-010**: Adding SONiC MUST NOT alter the behaviour of the existing Cisco, Arista, Dell or Juniper fabrics or their rendered configurations.
- **FR-011**: The reference solution MUST ship an overlay tenant scoped to the SONiC fabric, carrying at least one gateway-bearing segment and one L2-only segment, so that SONiC leaf configurations actually exercise the tenant overlay. Without it, no SONiC leaf renders any overlay configuration and FR-007 is only vacuously satisfiable.

**Verification note**: FR-006, FR-007 and FR-008 are verified by human review of rendered configurations, not by automated tests. This matches the existing four vendors, none of which has configuration-template tests. See Out of Scope.

### Key Entities

No new kinds of thing are introduced. Every entity below already exists in the domain model; this feature adds instances of them.

- **Manufacturer**: The hardware/OS maker a device type belongs to. Gains one instance, SONiC. Vendor groupings and configuration dialects are keyed off this, exactly as they already are for the four existing entries.
- **Device Type**: A switch model belonging to a Manufacturer. Gains four instances — three high-radix chipset generations, each serving both spine and super-spine tiers, and one access-leaf chipset — a wider set than the two-model-per-vendor pattern the other four vendors follow, because this feature deliberately models three chipset generations side by side rather than one.
- **Device Template**: A reusable switch definition that pre-declares a model's interfaces and their roles. Gains eight instances — spine and super-spine per chipset generation (three generations × two tiers), plus compute leaf and storage leaf — wider than the four-instance set the other vendors have, for the same reason.
- **Vendor group**: A grouping of generated devices by manufacturer, which the per-vendor configuration artifacts target. Gains one instance for SONiC.
- **Fabric / Pod / Rack**: The design levels an operator declares. Gains one SONiC fabric with its pods and racks.
- **Tenant / VRF / Segment**: The overlay-services design objects. Gains one tenant scoped to the SONiC fabric, with a VRF and segments — including one L2-only segment, matching the precedent set for the Juniper fabric.
- **Interface**: Gains SONiC-convention (alias-mode, `Eth1/N`) names. The two loopbacks keep their vendor-neutral logical names in the data model and are rendered in SONiC form by the configuration transform; interface **role** remains the reliable discriminator.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A reviewer with production SONiC/FRR experience reviews one generated leaf configuration and one generated spine configuration and raises **zero blocking structural findings** before the change is accepted. The review is scoped to SONiC syntax, the interface/VXLAN vs. EVPN-routing split, and EVPN/VXLAN structure; management addressing, interface MTU, and operational services such as authentication, time and logging are known simplifications shared by all vendors and are outside the review's remit.
- **SC-002**: A fifth vendor is added **without any change to the data model or to the generation logic** — only vendor data and one new configuration template. This is the measure of whether the multivendor design actually generalises; if it fails, every future vendor costs as much as the first.
- **SC-003**: Every generated SONiC switch has exactly two startup-configuration artifacts (`Startup configuration` and `FRR configuration`), and every existing Cisco, Arista, Dell and Juniper switch still has exactly one, unchanged.
- **SC-004**: A solutions engineer can present the full SONiC journey — design intent, generated switches and cabling, rendered SONiC configuration — without editing code and without running anything beyond the standard load command.

## Assumptions

- **Fidelity bar**: Generated SONiC configuration is held to the same standard as the four existing vendor dialects — recognisably correct to a network engineer on inspection, not deployable as-is. Simplifications the existing vendors already carry (management addressing, absent interface MTU, no operational services) are inherited deliberately rather than fixed here.
- **"Manufacturer" means vendor/config-dialect, not strictly legal hardware maker.** SONiC is an operating system that runs on disaggregated hardware from several makers, not a hardware manufacturer itself — a departure from Cisco, Arista and Juniper, who make both the hardware and the OS. This repository's existing pattern already treats the manufacturer field as the identity of the config dialect rather than a strict legal-manufacturer record (it is what every per-vendor group, template and artifact definition keys off). SONiC is modelled the same way: one manufacturer entry named "SONiC", with device types named after real SONiC-certified switch models, so hardware fidelity is preserved without implying a single company builds the OS and the box.
- **Hardware fidelity is held higher than configuration fidelity.** Switch models and their real port counts are modelled accurately, because the primary user recognises the hardware. Where hardware fidelity and demo tidiness conflict, hardware fidelity wins, matching the precedent set for Juniper.
- **Reviewer availability**: SC-001 places a reviewer with production SONiC/FRR experience on the critical path to acceptance. Identifying that person is a prerequisite; if none is available, the automated-validation decision recorded in Out of Scope should be revisited, because nothing else checks configuration correctness.
- **Demo growth**: The SONiC fabric grows the reference solution by roughly a fifth, mirroring the proportionate growth each prior vendor fabric added. No load-time or resource ceiling has been specified, and none has been measured.
- **Overlay model**: SONiC's EVPN/VXLAN implementation offers more than one way to express the control plane and data plane binding. The simpler, single-instance model is assumed appropriate for a reference solution, matching the precedent set for Juniper.
- **Switch models chosen**: for SONiC specifically, what matters for config generation is the chipset generation, not which ODM's box it ships in — every device type here is named after its chipset rather than a specific vendor SKU (research.md D2, D7). Three high-radix generations (Broadcom Tomahawk4/5/6) serve the spine and super-spine tiers, one visible in each of Fabric-E's three pods; a single access-chipset generation (Trident4-class) with an uplink port count matching the existing per-vendor pattern serves the leaf tier throughout. Real, publicly documented chipset generations and capacities, so the fabric stays comparable to the existing four side by side while also demonstrating that hardware generation is independent of role placement.
- **Existing behaviour is stable**: The domain model already carries no constraint on which manufacturers exist, so no data-model migration is expected for existing deployments beyond the additive demo data.

## Out of Scope

- **Automated validation of rendered configuration** — no configuration-template tests, golden files or SONiC/FRR config parsing. Correctness is established by human review (SC-001), consistent with the existing four vendors.
- **Mixed-vendor fabrics** — SONiC leaves inside a fabric of another make. This is already structurally possible, since switch models are chosen per-rack and per-pod, and is arguably a stronger story for a migrating evaluator. It is a separate feature with its own scope.
- **Deployable-quality configuration** — interface MTU, realistic management addressing, and operational services. Raising this bar would require raising all five vendors together and extending the data retrieved for configuration rendering.
- **Alternative SONiC EVPN/VXLAN control-plane or data-plane models.**
- **Changes to the Cisco, Arista, Dell or Juniper templates** to any new standard.
- **Testing against emulated or physical SONiC devices.**
- **Breakout/lane-level port modeling.** Port counts here reflect fixed, non-breakout front-panel usage on
  both chosen SKUs. The underlying chipset's breakout lane count (4 or 8, generation-dependent — see
  research.md D11) is recorded as documentation for a future breakout-modeling effort, not as queryable data;
  adding that would be a schema change no existing vendor in this repository has either, and is its own
  feature.
