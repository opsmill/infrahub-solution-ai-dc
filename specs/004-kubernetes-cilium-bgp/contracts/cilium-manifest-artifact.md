# Contract: Cilium Manifest Artifact

What the cluster artifact must contain. This is the **published contract with Vidra** and governs
FR-003, FR-004, FR-005, SC-002 and SC-004.

## Artifact identity — the part that must never change

| Property | Value | Why fixed |
|---|---|---|
| `artifact_name` | **`Cilium BGP Manifest`** | Typed into the `InfrahubSync` CR's `spec.source.artefactName` in every cluster that consumes it. Renaming it silently breaks every deployed cluster — Vidra matches on `name__values` and a no-match is not an error. |
| `content_type` | `application/yaml` | Vidra applies the body as Kubernetes resources. |
| `targets` | `kubernetes_clusters` group | One artifact per cluster. |

**Do not rename `artifact_name` without treating it as a breaking change.** The `.infrahub.yml`
definition key (`cilium_bgp_manifest`) is internal and may be renamed freely; `artifact_name` may not.

### One cluster per branch — a hard v1 bound

The artifact name is shared by **every** artifact the definition produces, not scoped per target.
Verified against a running stack: the existing cabling-plan definition yields three `CoreArtifact` rows
all named `Cabling Plan`, one per fabric.

Vidra's `InfrahubSync` carries no target or object selector — only `artefactName` — and its
`CreateArtifactsFromAPIResponse` iterates *every* returned edge rather than erroring on ambiguity. So
with two clusters, each cluster's Vidra syncs **both** clusters' documents into its own destination
namespace.

A foreign `CiliumBGPClusterConfig` is inert in the wrong cluster, since its `nodeSelector` matches no
local node — but it is still applied, and it stops being inert the moment a node-label value is reused
across clusters.

**Consequence for this contract**: v1 supports exactly one Cilium-consuming cluster per Infrahub
branch. Rendering is already correct for any number of clusters; it is *delivery* that cannot
disambiguate. Do not treat the N-cluster case as merely untested — it is wrong. Lifting the bound needs
either per-cluster artifact naming in Infrahub or a target selector in `InfrahubSync`.

## Document set

A single multi-document YAML body, `---`-separated. For a cluster with **N** eligible L3 members
(eligibility per `data-model.md` §5), the body holds exactly **N + 2** documents in this order:

1. N × `CiliumBGPClusterConfig` — one per eligible member, ordered by `node_selector`
2. 1 × `CiliumBGPPeerConfig`
3. 1 × `CiliumBGPAdvertisement`

When N = 0 the body holds **zero** documents — an empty (or whitespace-only) body, not an error, and
not the two shared documents on their own. A peer config with nothing referencing it and an
advertisement with nothing advertising it would be inert clutter, and FR-005 says "renders zero
documents".

Ordering is fixed and deterministic so the artifact checksum is stable across renders — the property
Vidra's checksum comparison depends on.

## 1. `CiliumBGPClusterConfig` — one per eligible L3 member

```yaml
apiVersion: cilium.io/v2
kind: CiliumBGPClusterConfig
metadata:
  name: <node_selector>
spec:
  nodeSelector:
    matchLabels:
      infrahub.io/server: <node_selector>
  bgpInstances:
    - name: <instance_name>
      localASN: <local_asn>
      peers:
        - name: <peer_name>
          peerASN: <peer_asn>
          peerAddress: <peer_address>
          peerConfigRef:
            name: cilium-peer
```

| Field | Source | Notes |
|---|---|---|
| `metadata.name` | `node_selector` | Unique by construction (derives from the unique service name), so no collision. Must be a valid RFC 1123 subdomain — service names in this repo already are. |
| `nodeSelector.matchLabels` | fixed key `infrahub.io/server` → `node_selector` | The operator must apply this label to the node themselves; out of scope here, documented in `quickstart.md`. |
| `bgpInstances[0].name` | `instance_name`, e.g. `instance-<local_asn>` | Deterministic. Cilium requires it unique within the document only. |
| `localASN` | server-side session `local_as` | The member's **own** ASN — per-member, never shared. Prevents AS-path loop rejection between members (user story 5). |
| `peers[0].name` | `peer_name`, e.g. `peer-<peer_asn>-leaf` | Deterministic; unique within the instance only. |
| `peerASN` | server-side session `remote_as` | The leaf's local AS. |
| `peerAddress` | leaf port `ip_address`, **host part only** | `10.0.0.1`, never `10.0.0.1/31`. Cilium expects a bare address. |
| `peerConfigRef.name` | fixed `cilium-peer` | Must match the `CiliumBGPPeerConfig` `metadata.name` below. `group`/`kind` omitted — they default to `cilium.io` / `CiliumBGPPeerConfig`. |

`localPort` is deliberately **omitted**: setting it makes Cilium listen, which needs
`CAP_NET_BIND_SERVICE` granted via a Helm value this feature does not own. Omitted, Cilium initiates
outbound only and peering still establishes.

## 2. `CiliumBGPPeerConfig` — exactly one, shared

```yaml
apiVersion: cilium.io/v2
kind: CiliumBGPPeerConfig
metadata:
  name: cilium-peer
spec:
  families:
    - afi: ipv4
      safi: unicast
      advertisements:
        matchLabels:
          advertise: cilium-bgp
```

`afi: ipv4` / `safi: unicast` mirrors the stored session's `address_family: ipv4_unicast` — the server
point-to-point pool is IPv4 and IPv6 is out of scope.

`advertisements.matchLabels` is a **label selector**, not a name reference. It must match the labels on
the `CiliumBGPAdvertisement` below; both sides are ours and must agree within this one manifest.

Omitted by design: `timers`, `authSecretRef`, `ebgpMultihop`, `gracefulRestart`, `transport`. All
optional, all out of scope, and the source of truth holds no data for any of them — defaulting them
here would assert configuration Infrahub does not know it holds.

## 3. `CiliumBGPAdvertisement` — exactly one, shared

```yaml
apiVersion: cilium.io/v2
kind: CiliumBGPAdvertisement
metadata:
  name: cilium-bgp-advertisements
  labels:
    advertise: cilium-bgp
spec:
  advertisements:
    - advertisementType: PodCIDR
```

`metadata.labels.advertise` must equal the peer config's
`families[].advertisements.matchLabels.advertise`.

`attributes` (communities, local preference) omitted — no data model exists for them.

Advertising Services / LoadBalancer IPs is explicitly out of scope, so `PodCIDR` is the only
advertisement type.

## Exclusions (FR-004)

A member contributes **no** document and appears **nowhere** in the body when it is L2, or when it is
L3 but lacks a resolvable server, an `ipv4_unicast` server-side session, either ASN, or a cabled
leaf-port IP. Exclusion is silent — no raise, no comment, no placeholder. A permanently broken member
is therefore detectable only as member count not matching document count, which the spec accepts.

## Verification (unit, per the PRD's Testing Decisions)

Parse the rendered body with `yaml.safe_load_all` and assert on structure, never on text:

| Check | Fixture |
|---|---|
| document count == N + 2; kinds and order | two eligible L3 members |
| every field of every cluster config matches the stored session and leaf address | two eligible L3 members |
| L2 member absent; its `node_selector` appears nowhere in the body | 2 × L3 + 1 × L2 |
| session-less / address-less L3 member absent, complete one present | 1 complete + 1 incomplete |
| zero documents, no raise | all-L2 cluster, and zero-member cluster |
| N vs N+1 document count differs by one | N and N+1 member fixtures |
| `peerAddress` follows the leaf | same member on a different leaf |
| `peerConfigRef.name` == peer config `metadata.name`; advertisement labels match the peer config selector | any N ≥ 1 fixture |

Do **not** assert on rendered whitespace, key order within a document, or template internals.
