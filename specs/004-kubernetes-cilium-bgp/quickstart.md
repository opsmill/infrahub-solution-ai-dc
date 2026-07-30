# Quickstart: Validating Kubernetes Clusters with Cilium BGP

End-to-end validation that declaring a cluster configures **both** sides of every member's peering.
Assumes the implementation (per `plan.md`, `data-model.md`, `contracts/`) is in place on a fabric
already built by the existing generators. Commands use the project's `invoke` tasks (`inv`) and `uv`.

Per the PRD's Testing Decisions this feature ships **unit tests only** — acceptance is manual, and this
is the manual procedure. Steps 5–7 are the acceptance verification for FR-003/FR-008 and SC-002/SC-004.

## Prerequisites

- `uv sync --all-packages` has run; Docker available.
- Familiarity with the existing build (`inv start`, `inv load`) — see `AGENTS.md`.
- The Server service (`specs/003-server-service/`) is in place and working — this feature builds on it.
- A fabric with racks and at least one Tenant → VRF exists (the seed in `objects/12_overlay.yml`).

## 1. Static checks

```bash
inv lint        # yamllint + ruff (ALL) + mypy (strict)
inv test        # pytest — new unit tests must pass
```

**Expected**: lint clean; all unit tests green. The new unit tests cover:

- the peering module — eligibility (L2 excluded, incomplete L3 excluded), deterministic ordering, and
  field mapping from session + cabling;
- the `node_selector` computed-attribute template (`server-cilium-worker-1` → `cilium-worker-1`);
- the transform's rendered output, parsed with `yaml.safe_load_all` and asserted on document count and
  field values.

**Expected also**: the existing Server service unit suite passes **untouched** — that is FR-009's check.
If `tests/unit/test_server_generator.py` or `tests/unit/test_servers.py` needed an edit, clustering has
leaked into member provisioning and the design constraint is broken.

## 2. Schema converges

```bash
inv load-schema     # loads schemas/ incl. new kubernetes.yml + server.yml edits
```

**Expected**: schema loads without error; the new kind `NetworkKubernetesCluster` exists and **is** a
`CoreArtifactTarget`; `NetworkServerService.kubernetes_cluster` exists as an optional cardinality-one
relationship; `NetworkServer.node_selector` exists as a `read_only` computed attribute.
`NetworkServer` is still **not** a `CoreArtifactTarget` and still not in `devices`.

## 3. Regenerate typed definitions *(required before the transform type-checks)*

```bash
# against the running stack, per the repo's existing procedure
# then:
inv lint        # mypy must now pass on the new transform and peering module
```

**Expected**: `src/infrahub_solution_ai_dc/protocols.py` gains `NetworkKubernetesCluster` and
`NetworkServer.node_selector`. Until this runs, `mypy .` fails on any code referencing them — see
`research.md` R6a.

## 4. Full build + cluster seed

```bash
inv load            # schema → menu → objects (incl. 09_kubernetes cluster + 13_servers members) → repository
inv start           # bring up the stack; generators run via triggers
```

**Expected after generators settle**: the `cilium-demo` cluster exists in the `kubernetes_clusters`
group with four members — three L3 (`cilium-worker-1/2/3`) and one L2 (`web-host-1`). Each L3 member has
a placed server with a /31, an allocated ASN, and a paired eBGP session; the L2 member has none of
those. `green-cilium-worker-1` / `green-web-host-1` remain **unclustered** and unaffected — FR-001's
"valid with none".

## 5. Both sides agree — the core acceptance check (SC-002)

For each of the three L3 members, compare the leaf's rendered startup config against the cluster's
rendered manifest.

**Leaf side** — open each member's leaf's `Startup configuration` artifact and note, for the
server-facing neighbour:

- the neighbour address (the *server's* /31 address)
- `remote-as` (the *member's* ASN)
- the leaf's own `router bgp <asn>` (the leaf's local AS)
- the leaf's server-facing interface address (the *leaf's* /31 address)

**Cluster side** — open the `cilium-demo` cluster's `Cilium BGP Manifest` artifact.

**Expected**: exactly **5 documents** — three `CiliumBGPClusterConfig`, one `CiliumBGPPeerConfig`, one
`CiliumBGPAdvertisement`. For each member's cluster config:

| Manifest field | Must equal |
|---|---|
| `spec.bgpInstances[0].localASN` | that member's ASN — the leaf's `remote-as` for it |
| `spec.bgpInstances[0].peers[0].peerASN` | that member's leaf's `router bgp` local AS |
| `spec.bgpInstances[0].peers[0].peerAddress` | that member's leaf's server-facing interface address, **without** the `/31` |
| `spec.nodeSelector.matchLabels["infrahub.io/server"]` | that member's `node_selector` (e.g. `cilium-worker-1`) |

100% agreement across all three members, with nothing reconciled by hand, is SC-002.

**Also expected** (US3 / FR-004): `web-host-1` appears **nowhere** in the manifest — not as a document,
not as a selector value. And the three `peerAddress` values are distinct, because each member is pinned
to its own rack (`Rack-A2-2`, `Rack-A2-3`, `Rack-A3-1`) and so sits on a different leaf.

Placement is pinned in `objects/13_servers.yml` rather than left to the generator, because several
services materializing at once all pick the same lowest-numbered free port and collide. See the
"Placement is pinned" section of `contracts/infrahub-registration.md` for the constraints on changing
those racks — in particular that a storage-template rack has no `role: server` ports at all.

## 6. Add and remove a member (US2 / FR-006)

```bash
# add a fourth L3 member pointing at cilium-demo, e.g. via the UI or:
#   infrahubctl object load <a file declaring one more l3 NetworkServerService with kubernetes_cluster: cilium-demo>
```

**Expected**: only the new member's fabric objects are created — no other member's server, /31, ASN,
session or leaf config changes, and the physical topology cascade does not re-run (SC-003). The cluster
artifact re-renders with **6 documents** (four cluster configs + the two unchanged shared documents).

Then remove that member and confirm the artifact returns to 5 documents with the removed member absent.

Then move an existing member to a different rack (set `rack` on its service) and confirm its
`peerAddress` follows the new leaf.

This step is also the **only** verification that FR-006's trigger half works. The unit tests prove the
manifest is a pure function of its members; that Infrahub actually re-renders on add / remove / move
rests on artifact data-dependency tracking, which nothing in this feature tests (`research.md` R7).

**Additionally, if Vidra is running** (step 8), remove the *last* L3 member and check what happens in
the cluster:

```bash
kubectl get ciliumbgpclusterconfigs
```

**Expected — but unverified**: the previously-synced `CiliumBGPClusterConfig` objects are deleted. This
feature's obligation ends at rendering zero documents (FR-005), which it does; whether an empty artifact
body makes Vidra *delete* what it previously applied or simply no-op was not verified and cannot be
without running the operator. If stale objects remain, that is a Vidra-side gap to report upstream, not
a defect in this feature — but it does mean the last member's peering is not withdrawn automatically.

## 7. Vidra's polling contract (US4 / FR-008)

```bash
curl -s -X POST \
  -H "Authorization: Bearer $INFRAHUB_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"variables": {"artifactname": "Cilium BGP Manifest"}}' \
  "$INFRAHUB_ADDRESS/api/query/ArtifactIDs?update_group=false&branch=main"
```

**Expected**: one `CoreArtifact` edge per cluster carrying the artifact, each with a non-null `id`,
`storage_id.id`, `checksum.value` and `name.value`. Run it twice against an unchanged fabric — the
checksum must be **identical** both times, which is what makes Vidra re-sync only on real change.

Note the exact shapes: variable `artifactname`, query path `ArtifactIDs`. Both are fixed by Vidra
(`contracts/graphql-queries.md`); a mismatch returns an empty edge list rather than an error.

## 8. Deploying to a real cluster *(outside this repository)*

Installing and operating Vidra, and labelling Kubernetes nodes, are **out of scope** for this feature.
Two things are the reader's responsibility:

1. **Label your nodes.** Each node must carry `infrahub.io/server=<node_selector>` matching the member
   whose peering it should adopt. Kubelet never sets this label:

   ```bash
   kubectl label node <node> infrahub.io/server=cilium-worker-1
   ```

   A missing or misspelled label yields a perfectly valid manifest that matches no node. The fabric
   cannot detect this — only the cluster side can, via `cilium bgp peers` showing no session.

2. **Point an `InfrahubSync` at the artifact by name**:

   ```yaml
   apiVersion: infrahub.operators.com/v1alpha1
   kind: InfrahubSync
   metadata:
     name: cilium-demo-bgp
   spec:
     source:
       infrahubAPIURL: "https://<your-infrahub>"
       targetBranch: "main"
       artefactName: "Cilium BGP Manifest"
     destination:
       namespace: "kube-system"
       reconcileOnEvents: true
   ```

   `artefactName` (Vidra's spelling) must match the artifact name exactly — it is a published contract,
   and renaming the artifact breaks every deployed cluster.

## Success checklist

- [ ] `inv lint` and `inv test` clean; existing Server service suite untouched (FR-009)
- [ ] Schema loads; `NetworkKubernetesCluster` is an artifact target; `node_selector` is read-only
- [ ] `protocols.py` regenerated; `mypy` passes
- [ ] Cluster seeds load; three L3 + one L2 members; unclustered services unaffected (FR-001)
- [ ] Manifest holds 5 documents; every ASN and address matches the leaf side (SC-002, SC-004)
- [ ] L2 member absent from the manifest (FR-004)
- [ ] Add / remove / move re-renders correctly, nothing else changes (FR-006, SC-003)
- [ ] `ArtifactIDs` returns id + storage id + checksum; checksum stable across runs (FR-008)
- [ ] No BGP value was typed anywhere by the operator (SC-001)
