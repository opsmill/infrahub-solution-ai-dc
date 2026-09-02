# Feature Specification: NVIDIA Cumulus Linux Vendor Support

**Feature Branch**: `006-cumulus-vendor-support`

**Created**: 2026-09-02

**Status**: Draft

**Input**: User description: "Add NVIDIA Cumulus Linux as a new supported network device vendor, following the exact pattern established by 002-multivendor-config and exercised end-to-end by 005-sonic-vendor-support (the immediately preceding vendor addition). Scope: add cumulus to the supported-vendors list, create a new startup-config template for Cumulus Linux's device syntax (ifupdown2-style /etc/network/interfaces bridge/VXLAN provisioning for the data plane, plus FRR for the EVPN/BGP control plane -- the same two-syntax split precedent SONiC established), register a Cumulus config transform and artifact definition targeting a new cumulus_devices group, add Cumulus manufacturer/device-type/device-template object data using real NVIDIA Spectrum-ASIC-based switch models (spanning multiple Spectrum chipset generations across spine/super-spine/leaf tiers, matching the breadth SONiC modelled across Tomahawk generations), and add a demo fabric/rack (plus a scoped overlay tenant with at least one gateway-bearing and one L2-only segment) so the new vendor is visible and inspectable end-to-end. No schema changes and no generator changes should be needed -- if either turns out to be necessary, that's a finding to flag, not something to silently do. Adding Cumulus MUST NOT alter the behaviour of the existing Cisco, Arista, Dell, Juniper or SONiC fabrics or their rendered configurations."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - A Cumulus Linux evaluator sees their hardware and their config (Priority: P1)

A network engineer from an organisation running NVIDIA Cumulus Linux on Spectrum-ASIC open
networking switches is shown the AI/DC reference solution by a solutions engineer. Today they
see five data-center fabrics built from Cisco, Arista, Dell, Juniper and SONiC hardware, and
generated configurations in five vendor dialects — none of which resembles the Debian-based,
NCLU/ifupdown2-driven operating system their own fleet runs. They have no way to assess whether
the solution understands their environment.

After this feature, the demo includes a sixth fabric built entirely from Cumulus-Linux-class
hardware. The evaluator can trace the same path they saw for the other vendors — a fabric
described as design intent, expanded into switches, interfaces and cabling, and rendered as a
device startup configuration — except the switches are NVIDIA Spectrum-ASIC hardware they
recognise, the interface names follow Cumulus Linux's `swp` convention, and the configuration
speaks Cumulus Linux's own two-file split: `/etc/network/interfaces` for bridges, VLANs and
VXLAN, and FRR for EVPN/BGP.

**Why this priority**: This is the only journey. The feature exists to let a Cumulus-shop
evaluator recognise their own environment; anything that stops short of a readable Cumulus
Linux configuration on recognisable hardware delivers nothing to that person.

The demo data is inside this slice rather than being a follow-on. A vendor capability with no
fabric using it is invisible to the evaluator and cannot be inspected — the demo fabric is both
the deliverable and the means of verifying it.

**Independent Test**: Load the reference solution, run generation for the Cumulus fabric, and
open the startup-configuration artifact on a Cumulus leaf switch and on a Cumulus spine switch.
Delivers the complete evaluator experience with no other work required.

**Acceptance Scenarios**:

1. **Given** the reference solution is loaded and generation has run for the Cumulus fabric,
   **When** an evaluator opens the startup-configuration artifact on a Cumulus leaf switch,
   **Then** it renders Cumulus Linux configuration containing the EVPN control plane, the VXLAN
   tunnel endpoint sourced from the leaf's tunnel loopback, one bridge-VLAN-to-VNI mapping per
   tenant segment, and a VRF binding for the tenant.

2. **Given** the same loaded solution, **When** an evaluator opens the startup-configuration
   artifact on a Cumulus spine or super-spine switch, **Then** it contains the EVPN
   control-plane configuration but **no** tenant VLAN-to-VNI mappings, no tunnel-endpoint
   configuration, and no tenant VRF bindings — because spines and super-spines are never tunnel
   endpoints.

3. **Given** the Cumulus fabric has been generated, **When** an operator inspects any generated
   Cumulus switch, **Then** it carries Cumulus Linux `swp`-convention interface names and
   belongs to both the general device grouping and the Cumulus vendor grouping.

4. **Given** the Cumulus fabric has been generated, **When** an operator inspects the cabling
   between a Cumulus rack and its pod, **Then** each leaf uplink port is cabled to a distinct
   spine downlink port, with no port paired twice and none left unintentionally unpaired.

### Edge Cases

- **Cumulus Linux configuration is split across two distinct syntaxes.** Interface, bridge, VLAN
  and VXLAN-tunnel provisioning follow the Debian `/etc/network/interfaces` (ifupdown2)
  convention, while the EVPN/BGP control plane follows FRR's own syntax. Unlike the three flat
  vendor dialects (a scoping mistake there produces one wrong line) and similar in kind to
  Junos's hierarchy risk and SONiC's own two-syntax split, mixing the two Cumulus syntaxes or
  emitting one inside the other is this feature's most likely failure mode.

- **Interface naming must use Cumulus Linux's real front-panel `swp` convention**
  (`swpN`, sequential per physical port, 1-indexed) rather than any breakout-suffixed naming
  Cumulus Linux also supports for split ports. Cabling and rendering must use the correct
  `swpN` name per port.

- **A tenant segment may have no anycast gateway.** A segment without a gateway is L2-only. Its
  bridge-VLAN-to-VNI mapping must still be rendered, but no routed (VRF-bound) SVI may be
  emitted for it.

- **Not every uplink port is cabled.** If the chosen Cumulus leaf model has more uplink ports
  than there are spine switches in a pod, surplus uplinks must render as present-but-disabled
  interfaces, consistent with how uncabled access ports already appear for every vendor.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST recognise Cumulus Linux as a supported vendor and place every device
  running it into a dedicated Cumulus vendor grouping.
- **FR-002**: System MUST reject devices whose manufacturer/vendor is not supported, naming the
  offending device, and MUST continue to do so for vendors other than Cumulus.
- **FR-003**: Users MUST be able to designate a fabric, pod or rack as Cumulus-built, and have
  generation produce Cumulus switches carrying Cumulus Linux `swp`-convention interface names.
- **FR-004**: System MUST place every generated Cumulus switch into both the general device
  grouping and the Cumulus vendor grouping.
- **FR-005**: System MUST cable Cumulus leaf uplinks to their pod's spine downlinks correctly,
  using Cumulus Linux's own interface-naming convention.
- **FR-006**: System MUST render exactly one Cumulus startup-configuration artifact for every
  Cumulus switch — not zero, not more than one.
- **FR-007**: System MUST render the tenant overlay — bridge-VLAN-to-VNI mappings, tunnel
  endpoint, routed SVIs and VRF bindings — only on leaf switches, and MUST NOT render any of it
  on spines or super-spines.
- **FR-008**: System MUST render the EVPN control plane on Cumulus switches of every tier,
  reflecting each switch's stored route-reflector role.
- **FR-009**: The reference solution MUST ship a Cumulus fabric of the same topology as the
  existing fabrics, so an evaluator sees a complete Cumulus environment rather than an isolated
  switch.
- **FR-010**: Adding Cumulus MUST NOT alter the behaviour of the existing Cisco, Arista, Dell,
  Juniper or SONiC fabrics or their rendered configurations.
- **FR-011**: The reference solution MUST ship an overlay tenant scoped to the Cumulus fabric,
  carrying at least one gateway-bearing segment and one L2-only segment, so that Cumulus leaf
  configurations actually exercise the tenant overlay. Without it, no Cumulus leaf renders any
  overlay configuration and FR-007 is only vacuously satisfiable.

**Verification note**: FR-006, FR-007 and FR-008 are verified by human review of rendered
configurations, not by automated tests. This matches the existing five vendors, none of which
has configuration-template tests. See Out of Scope.

### Key Entities

No new kinds of thing are introduced. Every entity below already exists in the domain model;
this feature adds instances of them.

- **Manufacturer**: The hardware/OS maker a device type belongs to. Gains one instance, Cumulus
  Linux. Vendor groupings and configuration dialects are keyed off this, exactly as they already
  are for the five existing entries.
- **Device Type**: A switch model belonging to a Manufacturer. Gains four instances — three
  high-radix Spectrum-ASIC generations, each serving both spine and super-spine tiers, and one
  access-leaf Spectrum-based model — mirroring the wider set SONiC modelled (three
  chipset-generation spine/super-spine models plus one leaf model) rather than the
  two-model-per-vendor pattern the other four flat-syntax vendors follow.
- **Device Template**: A reusable switch definition that pre-declares a model's interfaces and
  their roles. Gains eight instances — spine and super-spine per Spectrum generation (three
  generations × two tiers), plus compute leaf and storage leaf — matching SONiC's eight-instance
  breadth for the same reason.
- **Vendor group**: A grouping of generated devices by manufacturer, which the per-vendor
  configuration artifacts target. Gains one instance for Cumulus.
- **Fabric / Pod / Rack**: The design levels an operator declares. Gains one Cumulus fabric with
  its pods and racks.
- **Tenant / VRF / Segment**: The overlay-services design objects. Gains one tenant scoped to the
  Cumulus fabric, with a VRF and segments — including one L2-only segment, matching the precedent
  set for the Juniper and SONiC fabrics.
- **Interface**: Gains Cumulus Linux `swp`-convention (`swpN`) names. The two loopbacks keep
  their vendor-neutral logical names in the data model and are rendered in Cumulus Linux form by
  the configuration transform; interface **role** remains the reliable discriminator.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A reviewer with production Cumulus Linux/FRR experience reviews one generated leaf
  configuration and one generated spine configuration and raises **zero blocking structural
  findings** before the change is accepted. The review is scoped to Cumulus Linux syntax, the
  `/etc/network/interfaces` vs. FRR split, and EVPN/VXLAN structure; management addressing,
  interface MTU, and operational services such as authentication, time and logging are known
  simplifications shared by all vendors and are outside the review's remit.
- **SC-002**: A sixth vendor is added **without any change to the data model or to the
  generation logic** — only vendor data and one new configuration template. This is the measure
  of whether the multivendor design actually generalises; if it fails, every future vendor costs
  as much as the first.
- **SC-003**: Every generated Cumulus switch has exactly one startup-configuration artifact, and
  every existing Cisco, Arista, Dell, Juniper and SONiC switch still has exactly one, unchanged.
- **SC-004**: A solutions engineer can present the full Cumulus journey — design intent,
  generated switches and cabling, rendered Cumulus Linux configuration — without editing code
  and without running anything beyond the standard load command.

## Assumptions

- **Fidelity bar**: Generated Cumulus Linux configuration is held to the same standard as the
  five existing vendor dialects — recognisably correct to a network engineer on inspection, not
  deployable as-is. Simplifications the existing vendors already carry (management addressing,
  absent interface MTU, no operational services) are inherited deliberately rather than fixed
  here.
- **"Manufacturer" means vendor/config-dialect, not strictly legal hardware maker.** Cumulus
  Linux is an operating system that today ships as part of NVIDIA's Spectrum-based switch
  portfolio, not a hardware line in the way Cisco, Arista and Juniper are — a departure this
  repository already accepted once for SONiC. This repository's existing pattern already treats
  the manufacturer field as the identity of the config dialect rather than a strict
  legal-manufacturer record (it is what every per-vendor group, template and artifact definition
  keys off). Cumulus Linux is modelled the same way: one manufacturer entry named "Cumulus", with
  device types named after real NVIDIA Spectrum-ASIC switch models, so hardware fidelity is
  preserved without implying a separate hardware maker.
- **Hardware fidelity is held higher than configuration fidelity.** Switch models and their real
  port counts are modelled accurately, because the primary user recognises the hardware. Where
  hardware fidelity and demo tidiness conflict, hardware fidelity wins, matching the precedent
  set for Juniper and SONiC.
- **Reviewer availability**: SC-001 places a reviewer with production Cumulus Linux/FRR
  experience on the critical path to acceptance. Identifying that person is a prerequisite; if
  none is available, the automated-validation decision recorded in Out of Scope should be
  revisited, because nothing else checks configuration correctness.
- **Demo growth**: The Cumulus fabric grows the reference solution by roughly a sixth, mirroring
  the proportionate growth each prior vendor fabric added. No load-time or resource ceiling has
  been specified, and none has been measured.
- **Overlay model**: Cumulus Linux's EVPN/VXLAN implementation offers more than one way to
  express the control plane and data plane binding (traditional bridge/VXLAN plus FRR, or the
  newer `vni-map`-integrated model). The simpler, single-instance bridge/VXLAN-plus-FRR model is
  assumed appropriate for a reference solution, matching the precedent set for Juniper and
  SONiC.
- **Switch models chosen**: what matters for config generation is the Spectrum-ASIC chipset
  generation, not a specific reseller's box, mirroring SONiC's chipset-first precedent. Three
  high-radix generations (Spectrum-2, Spectrum-3, Spectrum-4) serve the spine and super-spine
  tiers, one visible in each of the new fabric's three pods; a single access-leaf Spectrum-2
  model with an uplink port count matching the existing per-vendor pattern serves the leaf tier
  throughout. Real, publicly documented NVIDIA Spectrum switch families and capacities, so the
  fabric stays comparable to the existing five side by side while also demonstrating that
  hardware generation is independent of role placement. Exact model numbers are finalized during
  planning research.
- **Existing behaviour is stable**: The domain model already carries no constraint on which
  manufacturers exist, so no data-model migration is expected for existing deployments beyond
  the additive demo data.

## Out of Scope

- **Automated validation of rendered configuration** — no configuration-template tests, golden
  files or Cumulus Linux/FRR config parsing. Correctness is established by human review
  (SC-001), consistent with the existing five vendors. Accepted with open eyes: the two-syntax
  split has a structural failure mode the single-syntax dialects do not.
- **Mixed-vendor fabrics** — Cumulus leaves inside a fabric of another make. This is already
  structurally possible, since switch models are chosen per-rack and per-pod, and is arguably a
  stronger story for a migrating evaluator. It is a separate feature with its own scope.
- **Deployable-quality configuration** — interface MTU, realistic management addressing, and
  operational services. Raising this bar would require raising all six vendors together and
  extending the data retrieved for configuration rendering.
- **Alternative Cumulus Linux EVPN/VXLAN control-plane or data-plane models** (e.g. the
  `vni-map`-integrated model).
- **Changes to the Cisco, Arista, Dell, Juniper or SONiC templates** to any new standard.
- **Testing against emulated or physical Cumulus Linux devices (e.g. Cumulus VX).**
- **Breakout/lane-level port modeling.** Port counts here reflect fixed, non-breakout
  front-panel usage on all chosen SKUs, consistent with the precedent set for SONiC.
