# EVPN overlay is scoped per-fabric

An EVPN overlay — a Tenant and its VRFs/Segments — belongs to exactly one Fabric. Fabric-A and Fabric-B are
independent EVPN domains, each with its own overlay ASN and its own VNI/route-target numbering. We chose
this because the two demo fabrics are independent 5-stage Clos networks, and a single iBGP ASN with
fabric-local VNI/RT numbering keeps allocation simple and collision-free within a domain.

## Considered Options

- **Per-fabric (chosen)** — tenancy objects reference their Fabric; identifiers are fabric-local.
- **Cross-fabric tenants** — rejected: would require Data Center Interconnect (inter-fabric EVPN gateways,
  route-target stitching, cross-ASN handling), a substantially larger feature with no demo driver today.

## Consequences

- Cross-fabric DCI is explicitly out of scope and is a documented future extension.
- ASN, L2VNI, L3VNI, and route-target allocation are all reasoned about within one Fabric.
