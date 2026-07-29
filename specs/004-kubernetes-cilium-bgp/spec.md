# Feature Specification: Model Kubernetes Clusters Spanning Multiple Servers and Render Cilium BGP CRDs

**Feature Branch**: `dga-release-1.11`

**Created**: 2026-07-29

**Status**: Draft

**Input**: PRD from [issue #64 comment](https://github.com/opsmill/infrahub-solution-ai-dc/issues/64#issuecomment-5121372690) — "Kubernetes clusters with Cilium BGP"

## User Scenarios & Testing *(mandatory)*

The Server service (`specs/003-server-service/`) connects **one** server to **one** leaf: it allocates a /31 and a private ASN, stores the paired eBGP session, and renders the leaf's neighbour into its startup config. A Kubernetes cluster is not one server — it is a set of servers spread across racks and leaves — and there is no way today to express that those servers belong together.

Worse, only the **fabric half** of each peering is automated. The fabric knows both ends of every session but exposes nothing the cluster can consume, so the Cilium side of the very same session is written by hand and drifts away from the source of truth it was derived from.

This feature lets an operator declare a **Kubernetes cluster** and point Server services at it as **cluster members**. Members may be L3 (BGP-speaking), L2, or a mix. Adding an L3 member provisions the fabric exactly as today — placement, /31, ASN, stored session, rendered leaf config — and the cluster gains a rendered **Cilium manifest** holding the mirror image of that peering: one `CiliumBGPClusterConfig` per L3 member with its own ASN and its own leaf's address, plus a shared peer config and advertisement. That manifest is an Infrahub artifact, which **Vidra** syncs into the cluster and reconciles. The operator types no BGP value on either side.

### User Story 1 - Declare a Cilium cluster and get both sides configured (Priority: P1)

An operator declares a Kubernetes cluster as a design object and creates N L3 Server services pointing at it. The fabric provisions each member exactly as a standalone L3 server — least-utilized rack, free leaf port, cabling, a /31, a private ASN, and the paired eBGP session — and the cluster carries a ready-to-deploy Cilium manifest that mirrors every one of those sessions from the cluster side.

**Why this priority**: This is the headline capability and closes the drift gap the source of truth exists to close. It exercises the full path — cluster modelling, member association, per-member ASN, and manifest rendering — and delivers standalone value even if no other story ships. Both halves of every peering come from one source and cannot disagree.

**Independent Test**: On a seeded fabric with racks and a tenant VRF, create a Kubernetes cluster plus three L3 Server services naming it; verify each member is placed with a /31, an ASN and a stored eBGP session pair, the leaf startup configs render their neighbours, and the cluster artifact contains three cluster-config documents whose ASNs and peer addresses match those sessions.

**Acceptance Scenarios**:

1. **Given** a fabric with racks and a tenant VRF, **When** an operator creates a Kubernetes cluster and three L3 Server services pointing at it, **Then** each member is placed on a leaf with a /31, an ASN and a stored eBGP session pair; the leaf startup configs render their neighbours; and the cluster carries one `application/yaml` artifact containing three `CiliumBGPClusterConfig` documents (each with that member's `localASN`, its leaf's `peerAddress`, and a `nodeSelector` matching that member's node selector), one `CiliumBGPPeerConfig`, and one `CiliumBGPAdvertisement` advertising `PodCIDR`.
2. **Given** the cluster and its members as declared above, **When** the operator inspects what they supplied, **Then** no BGP value was typed on either side — no ASN, no address, no neighbour statement.
3. **Given** each rendered `CiliumBGPClusterConfig`, **When** its fields are compared to that member's stored eBGP session, **Then** `localASN` equals the member's own ASN, `peerASN` equals its leaf's local AS, and `peerAddress` equals its leaf's /31 address.
4. **Given** only the shipped dataset, **When** a demoer loads it, **Then** a demo cluster and its members already exist, so the whole journey is demonstrable without hand-built data.

---

### User Story 2 - Add or remove a member on a live cluster (Priority: P2)

An operator grows an existing cluster by one worker, or removes one. Only that member's fabric objects change, and the cluster's manifest re-renders to match — one more (or one fewer) cluster-config document, with the shared peer config and advertisement unchanged. A removed member disappears from the manifest rather than leaving an orphaned peer behind.

**Why this priority**: Clusters are not declared once and frozen; they grow and shrink. Without this, growing a cluster remains a manual edit on the cluster side — exactly the hand-maintained mirror this feature removes. It depends on P1 existing but is independently demonstrable against an already-rendered cluster.

**Independent Test**: Starting from a cluster with three members and a rendered artifact, add a fourth L3 Server service naming the cluster; verify only that member is provisioned and the artifact re-renders with four cluster-config documents. Then remove it and verify the artifact returns to three.

**Acceptance Scenarios**:

1. **Given** a cluster with three members and a rendered artifact, **When** the operator adds a fourth L3 Server service pointing at the cluster, **Then** the fabric provisions only that member, and the artifact re-renders with four `CiliumBGPClusterConfig` documents and an unchanged shared peer config and advertisement.
2. **Given** a cluster with four members and a rendered artifact, **When** the operator removes one L3 member, **Then** the artifact re-renders without that member's document and no other member's document changes.
3. **Given** an L3 member placed on one rack, **When** the operator moves it to another rack or port, **Then** the artifact re-renders with the new leaf's `peerAddress`.

---

### User Story 3 - Mixed L2/L3 cluster (Priority: P3)

A cluster holds both bridged (L2) and BGP-speaking (L3) members. Only the BGP-speaking ones appear in the manifest; the L2 members are full cluster members from the operator's point of view but emit no peering, because they have none. A cluster whose members are all L2 — or which has no members at all — renders an empty manifest rather than failing.

**Why this priority**: Real clusters are not uniformly L3, and a mixed cluster must be expressible without emitting peering for hosts that have none. It refines P1's rendering rather than adding a new capability, so it ships last.

**Independent Test**: Render a cluster holding two L3 members and one L2 member; verify exactly two cluster-config documents exist and the L2 member appears nowhere. Render an all-L2 cluster and verify zero documents and no error.

**Acceptance Scenarios**:

1. **Given** a cluster with two L3 members and one L2 member, **When** the artifact renders, **Then** it contains exactly two `CiliumBGPClusterConfig` documents and the L2 member appears nowhere in it.
2. **Given** a cluster whose members are all L2, or which has no members, **When** the artifact renders, **Then** it contains zero cluster-config documents and raises no error.
3. **Given** a cluster with one complete L3 member and one L3 member lacking a stored session or leaf address, **When** the artifact renders, **Then** only the complete member is present and rendering does not fail.

---

### User Story 4 - Poll the artifact for change from outside (Priority: P3)

A Kubernetes platform engineer runs Vidra, which needs to know when the fabric actually changed before re-syncing. The repository exposes an artifact-identity query returning each artifact's id, storage id and checksum by name, so Vidra polls cheaply and re-syncs only on real change.

**Why this priority**: It is the deployment contract that makes the manifest consumable, but it is a thin read-only surface independent of how the manifest is rendered.

**Independent Test**: Run the artifact-identity query against a stack with a rendered cluster artifact and verify it returns the artifact's id, storage id and checksum for the artifact's name.

**Acceptance Scenarios**:

1. **Given** a stack with a rendered cluster artifact, **When** the artifact-identity query is run for that artifact's name, **Then** it returns the artifact's id, storage id and checksum.
2. **Given** an unchanged fabric, **When** the query is run twice, **Then** the checksum is identical both times.

---

### Edge Cases

- **Member moved** to another rack or port: the /31 and leaf change; the manifest re-renders with the new peer address, driven by the artifact's own data dependency.
- **Member removed**: the manifest re-renders without it and Vidra reconciles the deletion — the case a per-member artifact would handle badly, since a deleted artifact tells the cluster nothing.
- **Zero-member or all-L2 cluster**: empty manifest, not an error; removing the last L3 member correctly withdraws all peering.
- **Member mid-provisioning or permanently broken**: omitted from the manifest so the other members' valid peering still deploys. A permanently broken member is silently absent, detectable only as member count not matching document count.
- **Same service in two clusters**: impossible by cardinality.
- **Node selector collision**: impossible — it derives from the hostname, which derives from the unique service name.
- **Wrong or missing node label**: a valid manifest that matches no node. The fabric cannot detect this; only the cluster side can.
- **Members spanning VRFs or Fabrics**: permitted and unvalidated in v1 — members peer into whatever AS their own leaf presents, with no warning.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: A Server service MUST be associable with at most one Kubernetes cluster, and MUST remain valid with none. *Verify*: a service with no cluster loads; a second cluster is rejected by cardinality.
- **FR-002**: Every Server MUST expose a read-only node selector value derived from its hostname with the generator's `server-` prefix removed. *Verify*: render the computed-attribute template with `server-cilium-worker-1` and assert `cilium-worker-1`.
- **FR-003**: The system MUST render one `application/yaml` artifact per Kubernetes cluster containing one `CiliumBGPClusterConfig` per eligible L3 member — `localASN` = that member's ASN, `peerASN` = its leaf's local AS, `peerAddress` = its leaf's /31 address, and a `nodeSelector` matching that member's node selector on the `infrahub.io/server` label — plus one `CiliumBGPPeerConfig` (IPv4 unicast) and one `CiliumBGPAdvertisement` (`PodCIDR`). *Verify*: render a two-L3-member fixture, parse the YAML, assert document count and every field against the stored sessions.
- **FR-004**: The system MUST exclude L2 members, and MUST exclude L3 members lacking a complete session or leaf address, from the manifest. *Verify*: a fixture with one L2 member and one session-less L3 member produces neither, while complete members are present.
- **FR-005**: A cluster with no eligible L3 members MUST render an empty manifest rather than fail. *Verify*: an all-L2 cluster renders zero documents and raises nothing.
- **FR-006**: The cluster artifact MUST re-render when a member is added, removed, or moved to another rack or port. *Verify*: render an N-member fixture and an N+1-member fixture and assert the document count differs by one; render a fixture whose member sits on a different leaf and assert `peerAddress` follows.
- **FR-007**: Users MUST be able to declare a cluster and its members without supplying any BGP value — no ASN, no address, no neighbour. *Verify*: object data containing no BGP fields yields a complete manifest.
- **FR-008**: The repository MUST expose an artifact-identity query returning each artifact's id, storage id and checksum by name, so Vidra can poll for change. *Verify*: the query is registered and returns those three fields for the cluster artifact when run against a stack.
- **FR-009**: Member provisioning MUST remain unchanged — clustering MUST NOT alter placement, allocation, fail-loud validation, or idempotency of the Server service. *Verify*: the existing Server service unit suite passes untouched.

### Key Entities *(include if feature involves data)*

- **Kubernetes cluster** *(new)*: A design object grouping the Server services whose servers form one Kubernetes cluster. Owned by the operator; lifecycle independent of its members (it may exist empty). Inherits the artifact-target behaviour so it can carry the Cilium manifest, and joins a new `kubernetes_clusters` group that the artifact definition targets. **Requires governance review** — new node kind.
- **Server service** *(affected)*: Gains an optional, cardinality-one relationship to a Kubernetes cluster. Generator behaviour is otherwise untouched.
- **Server** *(affected)*: Gains a read-only **node selector** attribute, computed from its hostname. Remains excluded from device groups and from startup-config rendering.
- **BGP session** *(affected)*: Unchanged in shape, and now the single source both the leaf config and the Cilium manifest render from — the leaf renders one side, the manifest the mirror.
- **Cluster member**: Not a stored entity — the name for a Server service that points at a cluster.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Declaring a cluster of N L3 members requires zero operator-supplied BGP values on either side — no ASN, no peer address, no neighbour statement.
- **SC-002**: For every L3 member, the manifest's local ASN, peer ASN and peer address match that member's stored session and leaf address — 100% agreement across all members, with zero manual reconciliation.
- **SC-003**: Adding or removing one member changes that member's fabric objects and re-renders exactly one artifact; no other member's configuration changes and the physical topology cascade does not re-run.
- **SC-004**: A cluster of N L3 members produces exactly N cluster-config documents plus one peer config and one advertisement, valid against the Cilium resource definitions, applying with zero edits.
- **SC-005**: An operator goes from no cluster to a published manifest through a single Infrahub change, with zero logins to any server or switch.

## Assumptions

- Cilium's v2 BGP resources (`CiliumBGPClusterConfig`, `CiliumBGPPeerConfig`, `CiliumBGPAdvertisement`, `cilium.io/v2`), verified against the Cilium BGP control-plane configuration documentation. Peer address is expressible only per cluster-config document, which is why there is one per member; per-node overrides cannot carry it.
- Nodes carry an `infrahub.io/server` label matching each member's node selector. Kubelet never sets this label — something outside this repository applies it. Applying it is the reader's responsibility, documented in the feature quickstart; a mismatch yields a manifest that matches no node.
- Vidra is installed in the cluster and configured to sync the cluster artifact by name. **The artifact name is a published contract** — renaming it later breaks deployed clusters.
- One uplink per member — single-leaf attachment, as the Server service provides today. No multi-homing.
- Per-member ASN allocation continues from the existing global server ASN pool; the pool is sized for cluster growth rather than individual servers.
- No cluster-level tenancy constraint: members may span VRFs and Fabrics, unvalidated, because the correct constraint depends on how the cluster itself is configured.
- The shipped dataset gains a demo cluster with the existing `cilium-worker-1` seed retrofitted as a member, plus further members so the multi-member and mixed L2/L3 cases are demonstrable without hand-built data.
- The Fabric/Pod/Rack topology and the target VRF already exist before a cluster or its members are created, as the Server service already assumes.

## Out of Scope

- Advertising Services / LoadBalancer IPs, and allocating LB-IPAM pools from Infrahub — a larger separate need, and the obvious follow-up.
- IPv6 and dual-stack peering; the server point-to-point pool is IPv4.
- BGP timers, MD5 authentication, graceful restart, router-ID overrides — no data model exists for them, and defaulting them in a template would assert config the source of truth does not know it holds.
- Peer auto-discovery and ToR dynamic neighbours, which would replace the explicit per-neighbour leaf configuration that ADR-0005 stores.
- Validating or enforcing a cluster's VRF/Fabric scope.
- Labelling Kubernetes nodes; installing or operating Vidra.
- Multi-homed members; declaring N members from a single object (see issue #62, which owns the multi-member declaration ergonomics).
- Automated integration or end-to-end coverage — deferred until the integration foundation exists; acceptance is manual for now.
- Any new generator. Member provisioning stays with the existing Server service generator, per ADR-0002's standalone-generator boundary.

## Dependencies

- **Server service** (`specs/003-server-service/`, issues #51 / #55) — this feature builds directly on its placement, allocation and stored-session behaviour, and must leave it unchanged.
- **Stored BGP sessions** (ADR-0005) — the single source both the leaf config and the Cilium manifest render from.
- **Vidra** (<https://github.com/infrahub-operator/vidra>) — the consumer of the cluster artifact; runs outside this repository.
- A schema load plus a regeneration of the typed node definitions against a running stack, for the new node kind, relationship and computed attribute.
