# One CiliumBGPClusterConfig per Kubernetes cluster member

A Kubernetes cluster's Cilium BGP manifest holds one `CiliumBGPClusterConfig` per **eligible L3 member** —
each carrying that member's `localASN`, its leaf's `peerASN` and `peerAddress`, and a `nodeSelector`
narrowing it to that one member — followed by one shared `CiliumBGPPeerConfig` and one shared
`CiliumBGPAdvertisement`. A cluster of N eligible members renders N + 2 documents.

The tidier shape — one cluster config for the whole cluster, specialised per node — is not expressible.
Every member peers with its own leaf on its own /31, and **`peerAddress` exists only on
`CiliumBGPClusterConfig`**.

## Considered Options

- **One cluster config per member (chosen)** — the only shape that can carry a distinct peer address per
  node. Each document is scoped to its member by a `nodeSelector` on the `infrahub.io/server` label, whose
  value is the member's node selector.
- **One shared cluster config plus one `CiliumBGPNodeConfigOverride` per member** — rejected on a verified
  constraint rather than an assumption: the override kind can restate `localASN`, `peers[*].localAddress`,
  `localPort` and `routerID`, but has **no `peerAddress` field**, and Cilium documents the peering source
  as a route lookup of the address defined in the cluster config
  (`specs/004-kubernetes-cilium-bgp/research.md` R1).
- **`cilium.io/v2alpha1` with `CiliumBGPPeeringPolicy`** — rejected: superseded by the v2 resource set.

## Consequences

- Member count drives document count, so adding or removing a member changes the manifest's length rather
  than one field. Documents are ordered by node selector, and the leaf address is read in interface-name
  order, so an unchanged fabric renders byte-identically — the stability the consumer's checksum
  comparison depends on.
- The peer config ↔ advertisement link is a **label selector**, not a name reference, so both sides are
  ours to choose and must agree inside the single rendered body.
- The two shared documents are meaningful only alongside at least one cluster config, so a cluster with no
  eligible L3 member renders **zero** documents — not the two shared ones orphaned.
- `localPort` is omitted, so Cilium only initiates sessions. Setting it would require
  `CAP_NET_BIND_SERVICE` granted cluster-side, which this repository does not own; the leaf accepts or
  initiates either way.
- Eligibility is decided per member and an ineligible member is **omitted, not raised on** — the one place
  in this area that deliberately does not fail loud, so one mid-provisioning member cannot withhold valid
  config from the rest. Omissions are logged with the check they failed.
- Rendering is correct for any number of clusters; *delivery* is not. Every artifact of one definition
  shares one `artifact_name` and the consumer selects by name alone, which bounds v1 to one
  Cilium-consuming cluster per Infrahub branch (recorded beside the artifact definition in
  `.infrahub.yml`).
