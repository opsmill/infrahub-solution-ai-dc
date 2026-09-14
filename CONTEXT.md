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

**Generator target**:
A design object that carries a **checksum** — the `GeneratorTarget` schema generic, worn by Pod, Rack,
Tenant and Server service. Being a target is what lets a node _drive_ a Generator: `triggers.yml` watches
that attribute.
_Avoid_: trigger, watched node, subscriber.

**Checksum**:
The digest a Generator stamps on a **generator target** to declare what it produced, and thereby to ask
the next Generator to run. It is derived either over everything one run touched — the physical cascade,
where a Fabric stamps its Pods and a Pod stamps its Racks — or over an explicit set of produced object
ids, which is how the Overlay and Server generators stamp their own design object. It is written **only
when it changes**: re-stamping an unchanged digest re-fires the Generator's own trigger and the cascade
never settles. A Rack carries a checksum but stamps none, being the last tier.
_Avoid_: hash, version, revision (it identifies a _set of objects_, not a point in time).

**Vendor group**:
A `CoreStandardGroup` child of the `devices` group — one per **Manufacturer**
(`{manufacturer}_devices`, lowercased — e.g. `cisco_devices`) — whose direct members are the generated devices
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
A VXLAN Tunnel Endpoint — only **leaf** switches; sources VXLAN from a dedicated VTEP loopback
(role `vtep`, named `Loopback1` in the data model).
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

### Server attachment

**Server**:
A host attached to the fabric — a compute endpoint, never a network device. Owns its own ports (a
`ServerInterface`, ADR-0006), is excluded from **vendor groups** and from startup-config rendering, and
carries a **node selector**.
_Avoid_: device (a **NetworkDevice** is a switch), host, node (a Kubernetes "node" is this Server seen
from the cluster's side).

**Server service**:
A design object declaring one Server's attachment to the fabric: which **Segment** it joins, at which
layer (L2 or L3), and optionally which **Kubernetes cluster** it belongs to. Its Generator picks the
**Rack** and the free leaf port, cables it, and for an L3 service allocates a /31 and a server ASN and
stores the eBGP **BGP sessions** — the operator supplies no addressing.
_Avoid_: connection, attachment, port assignment (those are the implementation objects it produces).

### Kubernetes clustering

**Kubernetes cluster**:
A design object grouping the **Server services** whose servers form one Kubernetes cluster. Owned by the
operator, with a lifecycle independent of its members — it may exist with none. It is what the Cilium BGP
manifest is rendered _for_, one artifact per cluster, via the `kubernetes_clusters` group. It adds no
Generator of its own.
_Avoid_: k8s, group (a **vendor group** is unrelated), tenant (a **Tenant** is overlay tenancy and
unrelated).

**Cluster member**:
A **Server service** that points at a **Kubernetes cluster** — a name for a role, **not** a stored
entity of its own. A member is _eligible_ when it is L3 and fully provisioned; only eligible members
appear in the cluster's manifest, and an ineligible one is omitted rather than raised on, so a
half-provisioned member never withholds config from the rest.
_Avoid_: node, worker (those name the server as Kubernetes sees it, not the fabric-side record).

**Node selector**:
A Server's identity as Kubernetes sees it — read-only, derived from its hostname with the Generator's
`server-` prefix removed (`server-cilium-worker-1` ⇒ `cilium-worker-1`). It is the value the manifest
matches on through the `infrahub.io/server` label, and the name of that member's cluster-config
document. Putting the label on the node happens outside this repository.
_Avoid_: label, hostname (the selector is _derived_ from the hostname; the label is where it is used).

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
- A **Server service** attaches exactly one **Server** to one **Segment** through one **leaf** port, and
  belongs to at most one **Kubernetes cluster**.
- A **Kubernetes cluster** has zero or more **cluster members** (its **Server services**), each on its own
  **leaf** and its own /31, and each contributing one document to the cluster's manifest when eligible.
- A **Server** has exactly one **node selector**; the **BGP sessions** an L3 **Server service** stores are
  the single source that both the leaf's config and the cluster's manifest render from — opposite sides of
  the same peering.

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
  the router-id / iBGP source; **loopback1** (role `vtep`) is the VTEP source. `Loopback0`/`Loopback1` are
  **logical names carried in the data model**, not per-vendor interface names — the config transform renders
  them in vendor syntax (Junos: `lo0` unit 0 / unit 1). Interface **role** is the reliable discriminator.
- "Route reflector" was initially derived from tier ordering at render time — revised (ADR-0005): it is now
  **stored** as `NetworkDevice.route_reflector` plus a per-session `rr_client` flag; the tier ordering
  (super-spine → spine → leaf) is applied once by the generators when populating sessions.
- "Tenant" vs "Organization" — resolved: **Tenant** is an overlay-services owner; **Organization** is the
  existing manufacturer namespace. They are unrelated.
