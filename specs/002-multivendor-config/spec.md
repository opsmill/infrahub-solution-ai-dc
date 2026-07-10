# Feature Specification: Multivendor Per-Vendor Configuration

**Feature Branch**: `wvd-add-overlay` (no spec-kit branch hook; spec dir is 002-multivendor-config)

**Created**: 2026-07-08

**Status**: Draft

**Input**: User description: "True multivendor solution: render different configuration per
vendor (Cisco, Arista, Dell) using nested device groups, one shared generator, artifacts and
transforms mapped to vendor-specific groups. Also clean up the dataset: remove all
vendor-less devices/templates and make Fabric-A Cisco, Fabric-B Arista, and add Fabric-C on
Dell, so there are three single-vendor fabrics to choose from."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Per-vendor config from a single shared generator (Priority: P1)

A network engineer generates a fabric. Each device is automatically placed in its
manufacturer's device group, and its startup configuration is rendered from a template owned
by that vendor — not a single template applied to every make. The generators are not forked
per vendor; one generator per topology level resolves each device's vendor and routes it to
the right group.

**Why this priority**: This is the core capability. Without vendor-aware grouping and
rendering, nothing else about "multivendor" is real. It is independently valuable even
before the dataset is reshaped.

**Independent Test**: Generate any fabric containing more than one vendor; confirm every
device belongs to exactly its `{vendor}_devices` group and produces exactly one startup
config rendered from that vendor's template.

**Acceptance Scenarios**:

1. **Given** a fabric with Cisco, Arista, and Dell devices, **When** the generators run,
   **Then** each device is a member of both `devices` and its matching `{vendor}_devices`
   child group, and no device is in more than one vendor group.
2. **Given** those devices, **When** artifacts render, **Then** each device yields exactly
   one startup-config artifact, sourced from its vendor's template (none with zero, none
   with two).
3. **Given** a device whose manufacturer cannot be resolved, **When** the generator runs,
   **Then** generation fails with an error that names the offending device.

---

### User Story 2 - Choose a vendor by choosing a fabric (Priority: P2)

An author or demoer wants to exercise the solution on Cisco, Arista, or Dell. The shipped
dataset provides three clean single-vendor fabrics: Fabric-A (Cisco), Fabric-B (Arista), and
Fabric-C (Dell). No fabric contains vendor-less devices.

**Why this priority**: Turns the P1 capability into a usable, demonstrable dataset. Depends
on P1 being in place to be meaningful, but delivers the day-to-day value ("pick a vendor").

**Independent Test**: Load the dataset and generate each fabric; confirm Fabric-A is 100%
Cisco, Fabric-B 100% Arista, Fabric-C 100% Dell, and that a full load+generate completes
with zero vendor-resolution errors.

**Acceptance Scenarios**:

1. **Given** the shipped data, **When** Fabric-A / -B / -C is generated, **Then** every
   device in it has manufacturer Cisco / Arista / Dell respectively.
2. **Given** the shipped templates, **When** they are inspected, **Then** every object
   template declares a device type and no vendor-less template remains.
3. **Given** Fabric-A and Fabric-B contain storage racks, **When** they are generated,
   **Then** the storage leaves build on that fabric's vendor (Cisco/Arista storage-leaf
   templates exist).

---

### User Story 3 - Iterate one vendor's config in isolation (Priority: P3)

Having three per-vendor templates (initially near-identical), an engineer edits one vendor's
template to make it vendor-correct and verifies only that vendor's devices change.

**Why this priority**: Enables the follow-up work of actually diverging the templates
(correct EOS/OS10 syntax) safely; not required for the initial multivendor structure.

**Independent Test**: Edit a single vendor template; regenerate configs; confirm that
vendor's device configs changed and the other two vendors' configs have a zero-line diff.

**Acceptance Scenarios**:

1. **Given** three per-vendor templates, **When** only the Dell template is edited, **Then**
   only Dell devices' startup configs change; Cisco and Arista configs are unchanged.

### Edge Cases

- **Unresolvable vendor**: a device built from a template with no manufacturer → hard error
  naming the device (never a silent skip, never a default config).
- **Dual membership**: a device is in both the `devices` parent and a vendor child group;
  because no config artifact targets `devices`, it still renders exactly one config.
- **Interface renaming on re-vendor**: generic templates name interfaces `Ethernet[1-27]`
  while vendor templates use `Ethernet1/[1-N]`; re-vendoring Fabric-A/B changes interface
  names, so stale interfaces could linger on a pre-existing stack. Handled by applying via a
  fresh load / regeneration rather than in-place migration.
- **Port-count headroom**: vendor spine/super-spine templates (64 ports) exceed the generic
  ones (32) and the fabrics' super-spine counts (6/4), so cabling has capacity.
- **"Fabric"-role pods** (`Pod-A1/B1/C1`) reference no switch template → unaffected by
  re-vendoring.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The solution MUST expose three vendor device groups — `cisco_devices`,
  `arista_devices`, `dell_devices` — as children of the existing `devices` group.
- **FR-002**: The topology generators MUST resolve each generated device's manufacturer and
  make the device a member of both `devices` and the matching `{vendor}_devices` child
  group, without forking the generator per vendor.
- **FR-003**: The solution MUST render device startup config from three per-vendor
  templates/transforms, one artifact definition per vendor group, and MUST remove the single
  `devices`-targeted config artifact so each device renders exactly one startup config.
- **FR-004**: Generation MUST fail with a clear error identifying the device when its
  manufacturer cannot be resolved.
- **FR-005**: Every shipped object template MUST declare a device type; the five vendor-less
  templates (`spine-switch`, `super-spine-switch`, `Generic Switch`, `leaf-switch-compute`,
  `leaf-switch-storage`) MUST be removed.
- **FR-006**: The shipped dataset MUST define each fabric as single-vendor — Fabric-A =
  Cisco, Fabric-B = Arista, Fabric-C (new) = Dell.
- **FR-007**: The solution MUST provide Cisco and Arista storage-leaf templates (reusing the
  existing Cisco/Arista leaf device types, mirroring the Dell storage leaf's port-profile
  split) so storage racks in Fabric-A/B build on-vendor.
- **FR-008**: Fabric-C MUST mirror the current Fabric-B topology (super-spine count, pods,
  rack layout) using Dell templates.

### Key Entities *(include if feature involves data)*

- **`devices` group**: existing standard group; becomes the organizational parent.
- **`{vendor}_devices` groups** (new ×3): vendor children of `devices`; direct membership
  drives per-vendor artifact targeting.
- **Manufacturer** (existing: Dell, Cisco, Arista): the resolution key; the vendor group name
  derives from the manufacturer name.
- **Startup-config template/transform/artifact**: one shared today → three per-vendor,
  sharing the existing config GraphQL query.
- **Object templates**: gain 2 (Cisco/Arista storage leaf), lose 5 (generic).
- **Fabric-A/-B/-C**: A re-vendored generic→Cisco, B re-vendored Dell→Arista, C new = Dell
  mirror of today's B. Per-fabric addressing/ASN auto-allocated by the fabric generator.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of generated devices belong to exactly one vendor group matching their
  manufacturer.
- **SC-002**: 100% of generated devices render exactly one startup-config artifact.
- **SC-003**: Editing a single vendor template changes only that vendor's device configs and
  produces a zero-line diff on the other two vendors' configs.
- **SC-004**: A device with an unresolvable manufacturer fails generation with an error
  naming the device — 0 silent skips.
- **SC-005**: 100% of shipped object templates declare a device type (0 vendor-less).
- **SC-006**: Generating Fabric-A yields 100% Cisco devices; Fabric-B 100% Arista; Fabric-C
  100% Dell.
- **SC-007**: A full load + generate of Fabrics A/B/C completes with 0 vendor-resolution
  errors.

## Assumptions

- Applied to a freshly loaded stack (or `inv destroy` + reload); in-place cleanup of
  already-generated generic devices/interfaces is out of scope.
- The three per-vendor templates start functionally identical to today's NX-OS template;
  making Arista (EOS) and Dell (OS10) syntax actually correct is deferred to follow-up work
  (User Story 3 enables it).
- The generator stays one class per topology level (fabric/pod/rack) — "shared generator"
  means not forking per vendor, plus a small manufacturer-resolution step.
- Splitting `cabling_plan` or `computed_interface_description` per vendor, mixed-vendor
  fabrics, and homogenizing A/B/C to one identical topology are out of scope for v1.
- Open item (non-blocking): whether Infrahub artifact targeting cascades to child-group
  members. Not required, because the generator stamps parent + child membership directly.
- Follow-up (non-blocking): add a "Vendor group" entry to `CONTEXT.md` (child of `devices`,
  one per Manufacturer; "vendor" used interchangeably with "Manufacturer"). Proposed during
  grilling, not yet applied.
