# Feature Specification: EVPN/VXLAN Overlay for the AI/DC Fabric

**Feature Branch**: `001-evpn-overlay`

**Created**: 2026-06-29

**Status**: Draft

**Input**: User description: "Add the capability to define and run an EVPN/VXLAN overlay on the AI/DC data-center fabric solution — multi-tenant Layer-2 and Layer-3 network services on top of the existing fabric, with the device configuration generated automatically."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Provision a routed multi-tenant overlay service (Priority: P1)

A network operator declares a **tenant** with one **routing instance (VRF)** and one or more **routed
segments** (each a Layer-2 network with its own subnet and default gateway). The solution allocates all the
overlay identifiers, places the service on the fabric's leaf switches, and produces the per-device
configuration that bridges each segment across the fabric and routes between the tenant's segments — while
keeping the tenant isolated from every other tenant.

**Why this priority**: This is the headline value — turning declarative tenant intent into a complete,
working EVPN overlay with no manual per-device configuration. It is the smallest slice that delivers a
usable multi-tenant L2+L3 service and stands alone as an MVP.

**Independent Test**: Declare one tenant with one VRF and two routed segments, run the generation, and
inspect the generated configuration on the leaf switches: both segments are bridged fabric-wide, each has a
local default gateway on every leaf, and the two segments can route to each other within the tenant. No
overlay identifiers were entered by hand.

**Acceptance Scenarios**:

1. **Given** a built fabric with no overlay services, **When** an operator declares a tenant with a VRF and
   two routed segments and runs generation, **Then** every leaf switch receives configuration that bridges
   both segments, provides each segment's default gateway locally, and routes between the two segments
   within the tenant.
2. **Given** two tenants each with a routed segment, **When** generation runs, **Then** the generated
   configuration keeps the two tenants' traffic isolated (no route exchange between them).
3. **Given** an operator declares a segment, **When** generation runs, **Then** the segment's overlay
   identifiers, VLAN, and route-target values are allocated automatically with no collisions and are
   recorded as queryable data.
4. **Given** an operator inspects the spine and super-spine switches, **When** generation runs, **Then**
   those switches participate in the overlay control plane but carry no tenant segment or gateway state.

---

### User Story 2 - Day-two change to an existing tenant (Priority: P2)

An operator adds (or modifies/removes) a segment on an existing tenant. The solution allocates identifiers
for the new segment and regenerates configuration only for the devices affected by the change, leaving every
unrelated device untouched.

**Why this priority**: Day-two operations are the core differentiator of the design-driven solution. Scoped,
non-disruptive change is what makes the overlay safe to evolve in production.

**Independent Test**: With an existing tenant already provisioned, add one segment to it and run generation;
confirm the affected leaf configurations gain the new segment while every other device's configuration is
unchanged.

**Acceptance Scenarios**:

1. **Given** a tenant with one segment already provisioned, **When** the operator adds a second segment and
   runs generation, **Then** only the devices carrying that tenant's segments are reconfigured and all other
   device configurations remain identical.
2. **Given** an existing segment, **When** the operator removes it, **Then** the segment's configuration is
   removed from the devices that carried it and its allocated identifiers are released.

---

### User Story 3 - Control segment reach: rack-scoped placement and L2-only segments (Priority: P3)

An operator controls where and how a segment exists: by default a segment is available on every leaf in the
fabric, but the operator may restrict it to specific racks; and a segment may be declared **L2-only** (no
default gateway) for cases where routing happens outside the fabric.

**Why this priority**: Adds operational precision and flexibility once the core service exists. Useful but
not required for the first usable overlay.

**Independent Test**: Declare one segment restricted to a single rack and one L2-only segment; confirm the
rack-scoped segment appears only on that rack's devices and the L2-only segment is bridged with no default
gateway anywhere.

**Acceptance Scenarios**:

1. **Given** a segment restricted to a chosen set of racks, **When** generation runs, **Then** only those
   racks' leaf switches receive the segment and other leaves do not.
2. **Given** a segment declared without a default gateway, **When** generation runs, **Then** the segment is
   bridged across its leaves with no gateway configured and no inter-subnet routing for that segment.
3. **Given** a segment with no rack restriction, **When** generation runs, **Then** it is available on every
   leaf in the fabric.

---

### Edge Cases

- **L2-only segment**: a segment without a default gateway is bridged only; no gateway and no inter-subnet
  routing are produced for it.
- **Removal**: deleting a tenant, VRF, or segment — or removing a rack from a segment's placement — removes
  the corresponding configuration from the affected devices and releases allocated identifiers.
- **Identifier exhaustion**: when an allocation range (segment IDs, routing IDs, VLANs, ASN) is exhausted,
  generation fails with a clear, actionable message rather than producing colliding or invalid values.
- **Empty or invalid placement**: a segment placed on a rack that has no leaf switches results in no device
  receiving it; this is surfaced rather than silently ignored.
- **No tenants defined**: a fabric with no overlay services still establishes the overlay control-plane
  baseline and continues to operate its existing underlay without disruption.
- **Conflicting requests**: two tenants are never given the same overlay identifiers; address-space overlap
  between tenants is not supported in this release (see Assumptions).

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Operators MUST be able to define a **tenant** scoped to a single fabric, owning one or more
  routing instances (VRFs).
- **FR-002**: Operators MUST be able to define **segments** (Layer-2 networks) within a VRF, each optionally
  carrying a subnet and a default gateway.
- **FR-003**: The system MUST automatically allocate all overlay identifiers — segment identifiers, routing
  identifiers, VLANs, fabric routing number (ASN), and route-target values — from managed ranges, with no
  manual assignment and no collisions within a fabric.
- **FR-004**: For routed segments, the system MUST provide a **distributed default gateway** — the same
  gateway present on every leaf that carries the segment — so a host's gateway is always local.
- **FR-005**: The system MUST support **L2-only segments** (no default gateway) that are bridged across the
  fabric without inter-subnet routing.
- **FR-006**: The system MUST enable **inter-subnet routing between segments within the same tenant** and
  MUST keep **different tenants isolated** from one another.
- **FR-007**: The system MUST generate complete per-device configuration that realizes the overlay on the
  **leaf** switches; **spine** and **super-spine** switches MUST participate in the overlay control plane but
  MUST NOT carry tenant segment or gateway state.
- **FR-008**: By default a segment MUST be available on **every leaf in the fabric**; operators MUST be able
  to **restrict a segment to specific racks**, in which case only those racks' leaves receive it.
- **FR-009**: A change to a tenant, VRF, or segment MUST regenerate configuration for **only the affected
  devices**, leaving all unrelated device configurations unchanged.
- **FR-010**: The overlay MUST **coexist with the existing fabric build and underlay** — adding the overlay
  must not disrupt how fabrics, pods, and racks are currently generated, nor existing device reachability.
- **FR-011**: All allocated overlay identifiers and routing values MUST be retained as **queryable data**
  (the system of record), inspectable independent of the generated configuration.
- **FR-012**: Each fabric MUST be an **independent overlay domain** with its own routing number and
  identifier space; cross-fabric interconnect is out of scope for this release.
- **FR-013**: The overlay design MUST be **extensible to an alternative control-plane mode in the future**
  without redefining the tenant/VRF/segment model operators interact with.
- **FR-014**: Provisioning, changing, and removing overlay services MUST follow the **same scoped, branch-
  based, reviewable workflow** the solution already uses for fabric changes (e.g. adding a rack).

### Key Entities *(include if feature involves data)*

- **Tenant**: An owner of overlay network services, scoped to one fabric; owns one or more VRFs.
- **VRF (routing instance)**: A tenant's isolated Layer-3 routing domain; owns one or more segments and
  defines the boundary for inter-subnet routing and isolation.
- **Segment**: A Layer-2 network (one VLAN mapped to one overlay identifier), optionally with a subnet and a
  default gateway; belongs to one VRF; may be available fabric-wide or restricted to specific racks.
- **Anycast gateway**: A segment's default gateway, identical on every leaf that carries the segment.
- **Overlay identifiers**: The automatically managed numbering (segment/routing identifiers, VLANs, fabric
  routing number, route targets) that the system allocates and records.
- **Fabric / Leaf / Spine / Super-spine**: The existing fabric and switches the overlay is realized on;
  leaves carry tenant state, spines and super-spines carry only control-plane participation.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: An operator can provision a new tenant with a routed segment and obtain complete, correct
  device configuration in a **single scoped action**, without manually assigning any overlay identifier.
- **SC-002**: **100%** of overlay identifiers (segment/routing identifiers, VLANs, route targets, fabric
  routing number) are auto-allocated with **zero collisions** across a fabric.
- **SC-003**: Adding or changing a segment on an existing tenant reconfigures **only the affected devices**
  — **zero** changes appear in unrelated device configurations.
- **SC-004**: Hosts in two segments of the **same tenant** can reach each other (routed), while hosts in
  **different tenants** cannot — verifiable from the generated configuration.
- **SC-005**: A segment can be made **fabric-wide or restricted to chosen racks**, and a restricted segment
  appears **only** on those racks' leaf switches.
- **SC-006**: Introducing the overlay causes **no change** to the previously generated underlay
  configuration or to the existing fabric/pod/rack build behavior.
- **SC-007**: An L2-only segment is bridged across the fabric with **no gateway** produced, confirming both
  routed and bridge-only services are supported.

## Assumptions

- **Per-fabric scope**: An overlay service belongs to a single fabric; cross-fabric interconnect (DCI) is out
  of scope for this release.
- **Single control-plane design initially**: The first release uses the fabric's existing underlay routing
  plus one overlay control-plane design; an alternative mode is a documented future extension (FR-013).
- **Non-overlapping tenant addressing**: Tenant address spaces are unique within a fabric in this release;
  overlapping per-tenant address space is a future extension.
- **Configuration target**: Generated overlay configuration extends the solution's existing per-device
  configuration artifact and follows the configuration syntax style already used by the solution.
- **Distributed (symmetric) routing**: Routed segments use a distributed anycast gateway on every carrying
  leaf rather than centralized routing.
- **Out of scope**: External/border connectivity (to WAN/internet), host/endpoint attachment modeling, and
  per-tenant overlapping address space.
- **Reuses existing fabric model**: The overlay builds on the existing Fabric → Pod → Rack hierarchy and the
  switches it already generates; it does not change that topology.
