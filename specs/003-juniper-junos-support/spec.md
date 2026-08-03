# Feature Specification: Juniper / Junos Vendor Support

**Feature Branch**: `wvd-20260727-add-juniper-support`

**Created**: 2026-07-27

**Status**: Draft

**Input**: User description: "Add support for Juniper Junos devices to the AI/DC reference solution — device templates, configuration artifacts and supporting data, reaching parity with the existing Cisco, Arista and Dell support."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - A Juniper evaluator sees their hardware and their config (Priority: P1)

A network engineer from a Juniper-standardised organisation is shown the AI/DC reference solution by a solutions engineer. Today they see three data-center fabrics built from Cisco, Arista and Dell hardware, and generated configurations in three vendor dialects — none of which they can judge. They have no way to assess whether the solution understands their environment.

After this feature, the demo includes a fourth fabric built entirely from Juniper hardware. The evaluator can trace the same path they saw for the other vendors — a fabric described as design intent, expanded into switches, interfaces and cabling, and rendered as a device startup configuration — except the switches are Juniper models they recognise, the interface names follow Junos conventions, and the configuration is Junos.

**Why this priority**: This is the only journey. The feature exists to let a Juniper-shop evaluator recognise their own environment; anything that stops short of a readable Junos configuration on recognisable Juniper hardware delivers nothing to that person.

The demo data is inside this slice rather than being a follow-on. A vendor capability with no fabric using it is invisible to the evaluator and cannot be inspected — the demo fabric is both the deliverable and the means of verifying it.

**Independent Test**: Load the reference solution, run generation for the Juniper fabric, and open the startup-configuration artifact on a Juniper leaf switch and on a Juniper spine switch. Delivers the complete evaluator experience with no other work required.

**Acceptance Scenarios**:

1. **Given** the reference solution is loaded and generation has run for the Juniper fabric, **When** an evaluator opens the startup-configuration artifact on a Juniper leaf switch, **Then** it renders Junos hierarchical configuration containing the EVPN control plane, the VXLAN tunnel endpoint sourced from the leaf's tunnel loopback, one bridging entry per tenant segment with its L2 VNI, and a routing instance for the tenant VRF.

2. **Given** the same loaded solution, **When** an evaluator opens the startup-configuration artifact on a Juniper spine or super-spine switch, **Then** it contains the EVPN control-plane configuration but **no** tenant bridging entries, no tunnel-endpoint configuration, and no tenant routing instances — because spines and super-spines are never tunnel endpoints.

3. **Given** the Juniper fabric has been generated, **When** an operator inspects any generated Juniper switch, **Then** it carries Junos-convention interface names and belongs to both the general device grouping and the Juniper vendor grouping.

4. **Given** the Juniper fabric has been generated, **When** an operator inspects the cabling between a Juniper rack and its pod, **Then** each leaf uplink port is cabled to a distinct spine downlink port, with no port paired twice and none left unintentionally unpaired.

### Edge Cases

- **Leaf switches carry two interface-name families.** The Juniper leaf model has access ports and uplink ports in different Junos naming families. Ordering interface names alphabetically places the uplink family before the access family — the reverse of port order, and unlike every existing vendor whose ports share a single name family. Cabling must continue to pair the correct ports.

- **Not every uplink port is cabled.** The chosen Juniper leaf model has more uplink ports than there are spine switches in a pod. Surplus uplinks must render as present-but-disabled interfaces, consistent with how uncabled access ports already appear for every vendor.

- **A tenant segment may have no anycast gateway.** A segment without a gateway is L2-only. Its bridging entry and VNI must still be rendered, but no routed interface may be emitted for it.

- **A tenant VRF's transit VLAN is not used.** Junos symmetric routing binds the L3 VNI to the routing instance directly, so the transit VLAN carried in the data model is deliberately not rendered — matching two of the three existing vendors.

- **Junos configuration is hierarchical, not flat.** Unlike the three existing vendor dialects, where a scoping mistake produces one wrong line, a scoping mistake in nested configuration produces structurally invalid output. This is the feature's most likely failure mode.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST recognise Juniper as a supported manufacturer and place every device of that make into a dedicated Juniper vendor grouping.
- **FR-002**: System MUST reject devices whose manufacturer is not a supported vendor, naming the offending device, and MUST continue to do so for manufacturers other than Juniper.
- **FR-003**: Users MUST be able to designate a fabric, pod or rack as Juniper-built, and have generation produce Juniper switches carrying Junos-convention interface names.
- **FR-004**: System MUST place every generated Juniper switch into both the general device grouping and the Juniper vendor grouping.
- **FR-005**: System MUST cable Juniper leaf uplinks to their pod's spine downlinks correctly, despite leaf access and uplink ports belonging to different Junos interface-name families.
- **FR-006**: System MUST render exactly one Junos startup-configuration artifact for every Juniper switch — not zero, not more than one.
- **FR-007**: System MUST render the tenant overlay — bridging entries, tunnel endpoint, routed interfaces and routing instances — only on leaf switches, and MUST NOT render any of it on spines or super-spines.
- **FR-008**: System MUST render the EVPN control plane on Juniper switches of every tier, reflecting each switch's stored route-reflector role.
- **FR-009**: The reference solution MUST ship a Juniper fabric of the same topology as the existing Arista and Dell fabrics, so an evaluator sees a complete Juniper environment rather than an isolated switch.
- **FR-010**: Adding Juniper MUST NOT alter the behaviour of the existing Cisco, Arista or Dell fabrics or their rendered configurations.
- **FR-011**: The reference solution MUST ship an overlay tenant scoped to the Juniper fabric, carrying at least one gateway-bearing segment and one L2-only segment, so that Juniper leaf configurations actually exercise the tenant overlay. Without it, no Juniper leaf renders any overlay configuration and FR-007 is only vacuously satisfiable.

**Verification note**: FR-006, FR-007 and FR-008 are verified by human review of rendered configurations, not by automated tests. This matches the existing three vendors, none of which has configuration-template tests. See Out of Scope.

### Key Entities

No new kinds of thing are introduced. Every entity below already exists in the domain model; this feature adds instances of them.

- **Manufacturer**: A hardware maker. Gains one instance, Juniper. Vendor groupings and configuration dialects are keyed off this.
- **Device Type**: A switch model belonging to a Manufacturer. Gains two instances — a high-radix model serving both spine and super-spine tiers, and an access-leaf model — mirroring the two-model-per-vendor pattern the existing vendors follow.
- **Device Template**: A reusable switch definition that pre-declares a model's interfaces and their roles. Gains four instances — spine, super-spine, compute leaf and storage leaf — matching the per-vendor set the existing vendors have.
- **Vendor group**: A grouping of generated devices by manufacturer, which the per-vendor configuration artifacts target. Gains one instance for Juniper.
- **Fabric / Pod / Rack**: The design levels an operator declares. Gains one Juniper fabric with its pods and racks.
- **Tenant / VRF / Segment**: The overlay-services design objects. Gains one tenant scoped to the Juniper fabric, with a VRF and segments — including one L2-only segment. The existing Arista and Dell fabrics have no tenant, so this is the single deliberate divergence from mirroring them; without it no Juniper leaf renders overlay configuration at all. Scoped to the Juniper fabric only, since adding tenants elsewhere would change existing vendors' configurations and violate FR-010.
- **Interface**: Gains Junos-convention names. The two loopbacks keep their vendor-neutral logical names in the data model and are rendered in Junos form by the configuration transform; interface **role** remains the reliable discriminator.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A reviewer with production Junos experience reviews one generated leaf configuration and one generated spine configuration and raises **zero blocking structural findings** before the change is accepted. The review is scoped to Junos syntax, stanza placement and EVPN/VXLAN structure; management addressing, interface MTU, and operational services such as authentication, time and logging are known simplifications shared by all four vendors and are outside the review's remit.
- **SC-002**: A fourth vendor is added **without any change to the data model or to the generation logic** — only vendor data and one new configuration template. This is the measure of whether the multivendor design actually generalises; if it fails, every future vendor costs as much as the first three.
- **SC-003**: Every generated Juniper switch has exactly one startup-configuration artifact, and every existing Cisco, Arista and Dell switch still has exactly one, unchanged.
- **SC-004**: A solutions engineer can present the full Juniper journey — design intent, generated switches and cabling, rendered Junos configuration — without editing code and without running anything beyond the standard load command.

## Assumptions

- **Fidelity bar**: Generated Junos configuration is held to the same standard as the three existing vendor dialects — recognisably correct to a network engineer on inspection, not deployable as-is. Simplifications the existing vendors already carry (management addressing, absent interface MTU, no operational services) are inherited deliberately rather than fixed here.
- **Hardware fidelity is held higher than configuration fidelity.** Switch models and their real port counts are modelled accurately, because the primary user recognises the hardware. Where hardware fidelity and demo tidiness conflict, hardware fidelity wins — the surplus uplink ports are modelled because the model genuinely has them, and configurations already render uncabled ports for every vendor.
- **Reviewer availability**: SC-001 places a reviewer with production Junos experience on the critical path to acceptance. Identifying that person is a prerequisite; if none is available, the automated-validation decision recorded in Out of Scope should be revisited, because nothing else checks configuration correctness.
- **Demo growth**: The Juniper fabric grows the reference solution by roughly a third — from about 71 switches to about 94. No load-time or resource ceiling has been specified, and none has been measured.
- **Overlay model**: Junos offers more than one way to express EVPN/VXLAN. The simpler, single-instance model is assumed appropriate for a reference solution.
- **Switch models chosen**: a 64-port high-radix model for the spine and super-spine tiers, and a 48-port access model with eight uplink ports for the leaf tier — the closest Juniper equivalents to the models the existing three vendors use, so the fabrics stay comparable side by side.
- **Existing behaviour is stable**: The domain model already carries no constraint on which manufacturers exist, so no data-model migration is expected for existing deployments beyond the additive demo data.

## Out of Scope

- **Automated validation of rendered configuration** — no configuration-template tests, golden files or Junos parsing. Correctness is established by human review (SC-001), consistent with the existing three vendors. Accepted with open eyes: hierarchical configuration has a structural failure mode the flat dialects do not.
- **Mixed-vendor fabrics** — Juniper leaves inside a fabric of another make. This is already structurally possible, since switch models are chosen per-rack and per-pod, and is arguably a stronger story for a migrating evaluator. It is a separate feature with its own scope.
- **Deployable-quality configuration** — interface MTU, realistic management addressing, and operational services. Raising this bar would require raising all four vendors together and extending the data retrieved for configuration rendering.
- **Alternative Junos overlay models** and the tenant VRF transit VLAN.
- **Changes to the Cisco, Arista or Dell templates** to any new standard.
- **Testing against emulated or physical Juniper devices.**
