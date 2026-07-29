# Data Model: Kubernetes Clusters with Cilium BGP

**Feature**: `specs/004-kubernetes-cilium-bgp/`
**Date**: 2026-07-29

Scope of change: **one new node kind, one new relationship, one new computed attribute, one new
group.** Nothing existing changes shape. The BGP session model is untouched — it becomes the shared
source both the leaf config and the Cilium manifest render from.

---

## 1. `NetworkKubernetesCluster` *(new node)*

The cluster design object. Groups the Server services whose servers form one Kubernetes cluster, and
carries the rendered Cilium manifest as an artifact.

**File**: `schemas/kubernetes.yml` *(new)*

| Field | Kind | Optional | Notes |
|---|---|---|---|
| `name` | Text | no | `unique: true`; the human-friendly id and display label |
| `description` | Text | yes | Free-form operator note |

**Relationships**

| Name | Peer | Kind | Cardinality | Optional | Identifier |
|---|---|---|---|---|---|
| `members` | `NetworkServerService` | Generic | many | yes | `kubernetes_cluster__members` |

**Inheritance**: `CoreArtifactTarget` — required for the node to carry an artifact.

**Why it is not a `GeneratorTarget`**: there is no new generator (ADR-0002). The cluster is an
artifact target only.

**Lifecycle**: independent of its members. A cluster may exist with zero members (FR-005), and
deleting a cluster does not delete its members — the relationship is not `Component`.

**Group membership**: joins the new `kubernetes_clusters` standard group, which the artifact
definition targets.

### Validation rules

| Rule | Source | Enforced by |
|---|---|---|
| `name` unique | data model | schema `unique: true` |
| A cluster with zero members is valid | FR-005 | `optional: true` on `members` |
| No VRF/Fabric scope constraint across members | spec Assumptions, Out of Scope | deliberately unenforced |

---

## 2. `NetworkServerService.kubernetes_cluster` *(new relationship)*

**File**: `schemas/server.yml` *(extends)*

| Name | Peer | Kind | Cardinality | Optional | Identifier | order_weight |
|---|---|---|---|---|---|---|
| `kubernetes_cluster` | `NetworkKubernetesCluster` | Attribute | **one** | yes | `kubernetes_cluster__members` | 8000 |

`cardinality: one` is what makes FR-001's second half true by construction — "a second cluster is
rejected by cardinality" is enforced by Infrahub, not by generator code. `optional: true` is the first
half: a service with no cluster remains valid, so every existing seeded service keeps loading
unchanged.

The `identifier` is shared with `NetworkKubernetesCluster.members`, making the two ends the same
relationship viewed from either side.

**Not changed**: `layer`, `vrf`, `rack`, `leaf_interface`, `segment`, `server`. The `ServerGenerator`
never reads the new relationship — this is the mechanical basis of FR-009.

---

## 3. `NetworkServer.node_selector` *(new computed attribute)*

**File**: `schemas/server.yml` *(extends)*

```yaml
- name: node_selector
  kind: Text
  label: Node Selector
  read_only: true
  optional: true
  description: >-
    The Kubernetes node-label value identifying this server, derived from its hostname by
    dropping the generator's `server-` prefix. Put it on the node as
    `infrahub.io/server=<value>` so the rendered Cilium manifest matches.
  computed_attribute:
    jinja2_template: '{{ hostname__value | replace("server-", "", 1) }}'
    kind: Jinja2
  order_weight: 3500
```

> **Implementation note (found during T005/T009):** Infrahub rejects a `description` longer than
> **128 characters** (`string_too_long`), so the wording above and in §1 is longer than the schema will
> accept. Both shipped descriptions are shortened forms that keep the operator-facing instruction
> (`infrahub.io/server=<value>`); see `schemas/server.yml` and `schemas/kubernetes.yml` for the
> as-loaded text. The prose here is the intent, not a literal string to paste.

**Derivation**: `hostname` is `server-{service_name}` (`generators/generate_server.py:52-54`), so the
selector is the service name. Because `NetworkServerService.name` is `unique: true`, selector values
are unique by construction — this is what makes the spec's "node selector collision: impossible" edge
case a property rather than a hope.

**Why count-limited replace**: `replace("server-", "", 1)` strips only the leading occurrence. An
unanchored replace would mangle a service legitimately named e.g. `server-side-cache`.

**Precedent**: `NetworkInterface.index` in `schemas/device.yml:203-209` is the existing `read_only` +
`computed_attribute` + `kind: Jinja2` pattern; `tests/unit/test_computed_attribute.py` is the existing
way such a template is unit-tested (render it with `infrahub_sdk.template.Jinja2Template`, assert the
string).

**Not changed**: `NetworkServer` stays out of `devices` / `{vendor}_devices` and remains a non-target
for startup-config artifacts.

---

## 4. `kubernetes_clusters` *(new group)*

**File**: `objects/01_groups.yml` *(extends)*

```yaml
- name: kubernetes_clusters
```

Not parented under `devices` — a cluster is not a device, and the per-vendor startup-config artifacts
must never sweep it up. It is the `targets:` of the new artifact definition, mirroring how `fabrics` is
the target of the cabling plan.

---

## 5. `CiliumPeering` *(new in-memory record — not stored)*

The output of the pure peering module. Not an Infrahub node; the intermediate value that keeps
selection logic out of the renderer.

**File**: `src/infrahub_solution_ai_dc/clusters.py` *(new)*

| Field | Type | Source |
|---|---|---|
| `node_selector` | `str` | `NetworkServer.node_selector` |
| `local_asn` | `int` | server-side session `local_as` |
| `peer_asn` | `int` | server-side session `remote_as` |
| `peer_address` | `str` | leaf port `ip_address`, host part only (no `/31` suffix) |
| `instance_name` | `str` | derived, deterministic |

A `NamedTuple`, matching the `ProcessedInputData` convention in `transforms/cabling_plan.py`.

### Eligibility (FR-004)

A member yields a record only when **all** hold:

1. `service.layer == "l3"` — excludes L2 members.
2. The service resolves to a `NetworkServer`.
3. That server has a session with `address_family == "ipv4_unicast"`.
4. That session has non-null `local_as` **and** `remote_as`.
5. The server's cabling resolves to a leaf-port IP address.

> **Correction (found during T014).** Check 3 originally also required "whose `device` is the server".
> That clause is **redundant and must not be implemented**: `NetworkServer.bgp_sessions` is the inverse
> of `NetworkBGPSession.device` — both carry the schema identifier `device__bgp_session`
> (`schemas/routing.yml`), while `peer_device` uses the distinct `bgp_session__peer_device`. So every
> session reachable from a server is already that server's own side of the pair. It is also
> *unverifiable* from the transform's query, which selects no `device` field. Filtering on
> `address_family` alone is correct and complete.

> **Note on `peer_name`.** The record above carries `instance_name` but not the per-peer name. The
> artifact contract needs `peer-<peer_asn>-leaf`, which is derived in the transform from `peer_asn`
> rather than stored on the record — a rendering concern, not a selection one.

Failing any check **omits** the member — no raise (FR-004, FR-005). This is the one place the feature
deliberately does not fail loud, and the reason is in the spec: one mid-provisioning member must not
withhold valid config from the rest.

Omission is not, however, *silent*: the module **logs each omitted member and the check it failed**.
Without that, a permanently broken member is detectable only by manually comparing member count to
document count, which the spec concedes. A log line costs nothing, changes no rendered output, and
turns an invisible failure into a diagnosable one.

### Ordering — at both levels

**Across members**: sorted by `node_selector`. Deterministic ordering is what makes the artifact
checksum stable across renders, which is what makes Vidra's checksum comparison meaningful (FR-008).
Without it, an unordered member fetch would produce a new checksum on every render and Vidra would
re-sync forever.

**Within a member**: when resolving the leaf-port IP, iterate the server's interfaces **sorted by
interface name** and take the first eligible one — not simply "the first found", which is query order.
The spec assumes one uplink per member, so in practice there is one candidate. But a second cabled
interface (a management port, or leftovers mid-move) would otherwise let `peerAddress` flip between
renders, reintroducing exactly the checksum churn the across-member ordering exists to prevent.

### Value mapping

`local_asn`/`peer_asn` both come from the **server-side** session, where the generator writes
`local_as=server_asn, remote_as=overlay_asn` (`generators/generate_server.py:693-695`). One object
supplies both, so the two ASNs cannot disagree with the leaf's rendered config — the mechanism behind
SC-002.

`peer_address` comes from the cabling, not the session: `NetworkBGPSession` stores no addresses at
all. Path — server → `interfaces` → `link` → `endpoints` → the `NetworkInterface` end → `ip_address`,
stripped of its prefix length. It follows a move automatically because the link is what moves (FR-006).

---

## Entity relationships

```text
NetworkKubernetesCluster ──(members, many)──> NetworkServerService
        │                                              │
        │ CoreArtifactTarget                           │ (server, one)
        │                                              v
        └── carries ──> Cilium manifest artifact   NetworkServer
                              ^                     │  ├── node_selector (computed)
                              │                     │  ├── asn
                     rendered from                  │  ├── bgp_sessions ──> NetworkBGPSession
                              │                     │  │                     (local_as, remote_as,
                              └─────────────────────┘  │                      ipv4_unicast)
                                                       └── interfaces ──> ServerInterface
                                                                             └── link ──> NetworkLink
                                                                                    └──> leaf NetworkInterface
                                                                                            └── ip_address  (peerAddress)
```

---

## Migration and deferred regeneration

One schema load (`inv load-schema`), then a regeneration of
`src/infrahub_solution_ai_dc/protocols.py` against the running stack so the new kind, relationship and
computed attribute become typed.

**Ordering is not optional.** `protocols.py` is generated from the live schema, so until it is
regenerated it contains no `NetworkKubernetesCluster` and no `NetworkServer.node_selector`. CI runs
`mypy .`, which fails on any code referencing them. Schema + regeneration must land before the
peering module and transform that consume them (see `research.md` R6a — the PRD's "stale
generated-definitions check" does not exist; `mypy` is the real gate).

No data migration: every new field is optional or computed, so existing seeded objects remain valid
without edit. The only change to existing data is additive — `objects/13_servers.yml` gains
`kubernetes_cluster` on the `cilium-worker-1` service.
