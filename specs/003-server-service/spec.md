# Feature Specification: Connect L2/L3 Servers to Leaves via a Server Service

**Feature Branch**: `dga/feat-server-cilium-r9uuo`

**Created**: 2026-07-19

**Status**: Draft

**Input**: PRD from [issue #51 comment](https://github.com/opsmill/infrahub-solution-ai-dc/issues/51#issuecomment-5015062739) — "Connect L2/L3 servers to leaves via a server service"

## User Scenarios & Testing *(mandatory)*

The AI/DC solution turns minimal design intent into a complete data-center fabric — super-spines, spines, and leaves across Fabrics, Pods, and Racks with an EVPN/VXLAN overlay — but has no way to attach the workloads the fabric exists to serve. This feature lets an operator express "connect this server to the fabric" through a single design object and have the interfaces, cabling, IP addressing, and BGP materialized automatically.

The operator creates one **Server service** that captures the *request*: whether the server is **L2** or **L3**, which **VRF** (Tenant implied) it belongs to, and — optionally — a target Rack and leaf ports. The system materializes everything else.

### User Story 1 - L3 server (BGP-speaking / Cilium worker) (Priority: P1)

An operator declares a Server service of type L3 in a VRF, with no rack or ports chosen. The system produces the server and its interfaces, picks the least-utilized rack and a free leaf port, cables the link, allocates a dedicated /31 (rack-side address on the leaf) and a private server ASN, and creates an eBGP session on **both** the leaf and the server. The canonical case is a Kubernetes/Cilium worker that peers eBGP with its top-of-rack leaf to advertise its own CIDRs.

**Why this priority**: This is the headline capability and the primary motivating use case (Cilium worker onboarding). It exercises the full end-to-end path — placement, cabling, addressing, ASN allocation, and paired BGP — and delivers standalone value even if no other story ships.

**Independent Test**: On a seeded fabric with racks and a VRF, create an L3 Server service with no rack/ports; verify a server exists cabled to a leaf, a /31 is assigned on both ends, and paired eBGP sessions exist with correct remote-AS on each side — all in the service's VRF.

**Acceptance Scenarios**:

1. **Given** a fabric with racks and a VRF, **When** the operator creates an L3 Server service with no rack/ports, **Then** a server exists cabled to a leaf, a /31 is assigned on both ends, and an `ipv4_unicast` eBGP session exists on the leaf (remote-AS = server) *and* on the server (remote-AS = leaf), all in the service's VRF.
2. **Given** the same unchanged L3 Server service, **When** the generator runs again, **Then** nothing changes (empty diff).

---

### User Story 2 - L2 server (bridged into a Segment) (Priority: P2)

An operator declares a Server service of type L2 in a VRF, naming a target Segment, with rack/ports blank. The system produces the server, picks a rack, leaf, and access port, cables it, and attaches the leaf's Rack to the Segment's placement. There is no fabric-side BGP and no fabric-side IP — the host simply lands in the right VLAN / L2VNI.

**Why this priority**: Covers the plain-host case that does not need routing. It reuses placement and cabling from P1 but has a distinct, simpler materialization path (Segment placement instead of BGP/IP), so it is valuable but secondary to the BGP-speaking case.

**Independent Test**: On a VRF that has a Segment, create an L2 Server service; verify the server is cabled to a leaf whose Segment placement now includes that Rack, and that no BGP session or /31 was created.

**Acceptance Scenarios**:

1. **Given** a VRF with a Segment, **When** the operator creates an L2 Server service naming that Segment, **Then** a server is cabled to a leaf whose Segment placement now includes that Rack, and no BGP session or /31 was created.

---

### User Story 3 - Explicit placement (honor-or-fail) (Priority: P3)

An operator declares a Server service naming a specific Rack and/or leaf port(s) because of a physical constraint. The system uses exactly those if they are valid; if the rack has no free port, or the port is taken or has the wrong role, it fails loudly with a clear error and produces nothing.

**Why this priority**: An override for constrained placements layered on top of the automatic selection in P1/P2. It matters for real deployments but is not required for the core "one object in, connected server out" value.

**Independent Test**: Create a Server service naming an occupied leaf port; verify the generator errors clearly and creates no partial objects.

**Acceptance Scenarios**:

1. **Given** a Server service naming an occupied leaf port, **When** the generator runs, **Then** it errors clearly and creates no partial objects.
2. **Given** a Server service naming a valid free Rack and port, **When** the generator runs, **Then** exactly that Rack and port are used.

---

### Edge Cases

- No eligible rack with a free leaf port in the VRF's Fabric → fail loud, no partial materialization.
- L2 service naming a Segment that does not belong to the service's VRF → fail loud.
- Server-ASN pool or /31 prefix pool exhausted → fail loud with a pool-exhaustion error.
- L3 service that also names a Segment (contradictory intent) → reject as invalid.
- Concurrent services targeting the last free port on the same leaf → deterministic outcome; at most one wins, the other fails loud rather than double-allocating.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST produce a server implementation object plus its connectivity (interfaces and cabling to a leaf) from a single Server service.
- **FR-002**: System MUST select the least-utilized eligible Rack within the VRF's Fabric when no Rack is specified, using a deterministic tie-break.
- **FR-003**: System MUST select the lowest-numbered free leaf port with the `server` role when no port is specified.
- **FR-004**: System MUST honor an explicitly provided Rack and/or port, and MUST fail loud on invalid input, producing no partial objects.
- **FR-005** *(L3)*: System MUST allocate a /31 (rack-side address on the leaf), allocate a private server ASN, and create eBGP `ipv4_unicast` sessions on both the leaf and the server within the VRF, with the correct remote-AS on each side.
- **FR-006** *(L2)*: System MUST attach the leaf's Rack to the named Segment's placement, and MUST create no BGP session and no fabric-side IP.
- **FR-007**: A Server service MUST reference a VRF (Tenant implied); an L2 service MUST additionally resolve a Segment under that VRF.
- **FR-008**: The materialization MUST be idempotent — re-running on an unchanged Server service produces no changes.
- **FR-009**: The rendered leaf startup-config MUST include the server-facing interface and, for L3, the /31 and the eBGP neighbor, requiring no manual edits.

### Key Entities *(include if feature involves data)*

- **Server service** *(new)* — the design object recording the intent to connect a server: type (L2/L3), VRF, optional Rack, optional leaf ports, and — for L2 — a Segment. Owned by the operator; the trigger target for materialization.
- **Network server** *(new)* — the implementation object produced from a Server service: the concrete server and its interfaces. Distinct from a network device; never swept into per-vendor device groups or startup-config artifacts.
- **BGP peer** *(new, generalized)* — the shared notion that lets a BGP session point at either a network device or a network server as its endpoint, so leaf↔server sessions can be modeled alongside fabric sessions.
- **BGP session** *(affected)* — leaf↔server sessions use address family `ipv4_unicast` and are not route-reflector clients.
- **Segment** *(affected)* — L2 servers extend its Rack placement; its shape is otherwise unchanged.
- **Leaf/server interface** *(affected)* — server-facing leaf and server ports use the existing `server` role.
- **Pod** *(affected)* — gains a server /31 prefix pool and a server-ASN pool, alongside its existing pools.
- **IP prefix** *(affected)* — gains a new `server_p2p` role for the server point-to-point addressing.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: An L3 Server service with no rack/port specified yields a fully-connected server (link + /31 on both ends + eBGP session on both sides) with zero additional operator input.
- **SC-002**: An explicit Rack/port is honored exactly; an invalid choice fails loud with a clear message and creates no partial objects.
- **SC-003**: Re-running the generator on an unchanged Server service produces no changes.
- **SC-004**: The rendered leaf startup-config includes the server interface, /31, and eBGP neighbor (L3) with no manual edits.
- **SC-005**: Adding N L3 servers with no placement distributes them across racks such that no rack holds more than one more server than any other in the same Fabric.

## Assumptions

- The Fabric/Pod/Rack topology and the target VRF already exist before a Server service is created.
- Leaf devices have free access ports and an assigned ASN.
- Server ASNs are drawn from a private-AS range sized for the deployment.
- Only single-homed servers are in scope for v1 (no dual-homing, MLAG, LACP, or port-channels to servers).
- Only the leaf/fabric side is materialized; server-side OS/config rendering is out of scope.
- L3 handoff is BGP only; static-route handoff is out of scope.
- Server lifecycle beyond creation (decommission/move) is out of scope for v1.
