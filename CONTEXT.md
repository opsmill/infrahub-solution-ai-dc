# AI/DC Solution — Domain Context

The shared language for the Infrahub AI/DC reference solution: a design-driven automation that turns
minimal design intent into a complete data-center fabric (devices, IP allocations, cabling, config),
now extended with an EVPN/VXLAN overlay. This file defines the terms that carry specific meaning here so
they are used consistently in code, schema, and conversation.

## Language

### Design model

**Design object**:
An object that records _intent_ — what infrastructure should look like — and persists in Infrahub
independent of whether Generators have run (e.g. a Fabric, Pod, Rack, or Tenant).
_Avoid_: input, spec, template (a "device template" is a distinct supporting object).

**Implementation object**:
An object a Generator _produces_ from design intent — devices, interfaces, links, IP allocations, VNI/RT
allocations, materialized relationships.
_Avoid_: output, artifact (an "artifact" is specifically a rendered file like a startup config or cabling CSV).

**Generator**:
Code that reads one design object via a GraphQL query and produces its implementation objects;
idempotent and triggered by checksum changes.

**Vendor group**:
A `CoreStandardGroup` child of the `devices` group — one per **Manufacturer**
(`cisco_devices` / `arista_devices` / `dell_devices`) — whose direct members are the generated devices
of that make; the per-vendor startup-config artifacts target it. Membership is stamped by the generators
from each device's `device_type` manufacturer. _"Vendor" is used interchangeably with **Manufacturer** in
conversation; the stored entity is the Manufacturer._

### Physical hierarchy (5-stage Clos)

**Fabric**:
The top design level — owns the super-spine switches and the per-fabric overlay ASN; one independent EVPN
domain.

**Pod**:
The middle design level — owns the spine switches connected upward to super-spines.

**Rack**:
The bottom design level — owns the leaf switches connected upward to spines; the unit of scoped day-two
change and of overlay placement.

### Overlay tenancy

**Tenant**:
A design object representing one customer/workload owner of overlay services, scoped to exactly one Fabric;
owns VRFs.
_Avoid_: customer, organization (Organization is the manufacturer namespace), project.

**VRF**:
A tenant's L3 routing instance (IP-VRF), identified by an L3VNI and a route target; owns Segments.
_Avoid_: routing table, instance.

**Segment**:
A tenant L2 service (MAC-VRF) — one VLAN mapped 1:1 to one L2VNI, optionally with a subnet and anycast
gateway (IRB); belongs to one VRF.
_Avoid_: VLAN (the VLAN is one attribute of a Segment), network, subnet (the subnet is one attribute).

### EVPN constructs

**Underlay**:
The OSPF-routed IP fabric that provides loopback-to-loopback reachability between switches.

**Overlay**:
The iBGP L2VPN-EVPN control plane and VXLAN data plane carried on top of the underlay.

**VTEP**:
A VXLAN Tunnel Endpoint — only **leaf** switches; sources VXLAN from a dedicated VTEP loopback (loopback1).
Spines and super-spines are never VTEPs.

**L2VNI**:
The VXLAN Network Identifier for a Segment's MAC-VRF (L2 bridging / stretch).

**L3VNI**:
The VXLAN Network Identifier for a VRF's IP-VRF (symmetric IRB routing); needs a transit VLAN + core SVI.

**Anycast gateway**:
A Segment's default-gateway SVI configured identically on every carrying leaf (same IP + shared MAC), so a
host's gateway is always local. Optional per Segment (absent ⇒ L2-only Segment).

**Route reflector (RR)**:
A switch that reflects EVPN routes to its iBGP clients. Reflection is **hierarchical**: spines reflect for
their leafs and are themselves clients of the super-spines, which reflect for the spines. The RR role is
stored: `NetworkDevice.route_reflector` marks spines/super-spines, and each **BGP session** carries an
`rr_client` flag set by the generators from tier ordering (ADR-0005).

**BGP session**:
A directional `NetworkBGPSession` from a device toward a peer (local/remote AS, address family,
`rr_client`). Populated by the fabric/pod/rack generators along the actual cabling; the config transform
renders `router bgp` neighbors from these sessions.

## Relationships

- A **Fabric** contains many **Pods**; a **Pod** references many **Racks**; a **Rack** holds the **leaf**
  switches.
- A **Tenant** belongs to exactly one **Fabric** and owns one or more **VRFs**.
- A **VRF** owns one or more **Segments** and carries exactly one **L3VNI**.
- A **Segment** belongs to exactly one **VRF**, maps one VLAN to one **L2VNI**, and optionally has an
  **anycast gateway**.
- A **Segment** is carried by leafs in its placed **Racks** (or every leaf in the Fabric when placement is
  empty); the OverlayGenerator materializes this as a Device↔Segment relationship.
- Only **leaf** switches are **VTEPs**; **spines**/**super-spines** participate in the **overlay** control
  plane (as **route reflectors**) but never encapsulate.

## Example dialogue

> **Dev:** "When an operator declares a **Tenant** with a routed **Segment**, who allocates the **L2VNI**
> and the anycast-gateway IP?"
> **Domain expert:** "The **OverlayGenerator** does — those are **implementation objects**. The Tenant, its
> **VRF**, and the Segment are **design intent**; the Generator allocates the L2VNI from the pool, the
> subnet, and the gateway, and then materializes the Segment onto the carrying **leafs**."
> **Dev:** "And the spines?"
> **Domain expert:** "Spines never get the Segment — they're not **VTEPs**. They only reflect the EVPN
> routes as **route reflectors**. Encapsulation happens leaf-to-leaf."

## Flagged ambiguities

- "VLAN" was used loosely for both the L2 broadcast domain and the overlay service — resolved: the service
  is a **Segment**; "VLAN" refers only to its `vlan_id` attribute (and a VRF's `l3_vlan_id` transit VLAN).
- "Loopback" was ambiguous between the routing loopback and the tunnel source — resolved: **loopback0** is
  the router-id / iBGP source; **loopback1** (role `vtep`) is the VTEP source.
- "Route reflector" was initially derived from tier ordering at render time — revised (ADR-0005): it is now
  **stored** as `NetworkDevice.route_reflector` plus a per-session `rr_client` flag; the tier ordering
  (super-spine → spine → leaf) is applied once by the generators when populating sessions.
- "Tenant" vs "Organization" — resolved: **Tenant** is an overlay-services owner; **Organization** is the
  existing manufacturer namespace. They are unrelated.
