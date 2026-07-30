# Contract: `.infrahub.yml` Registration & Seed Data

How the cluster artifact registers with the Infrahub platform. Mirrors the existing `cabling_plan`
entries (the only other non-device artifact) in `.infrahub.yml` and `objects/01_groups.yml`.

## `.infrahub.yml` additions

**`queries`** — add two:

```yaml
  - name: cilium_manifest
    file_path: "./transforms/cilium_manifest.gql"

  - name: ArtifactIDs
    file_path: "./queries/artifact_ids.gql"
```

`ArtifactIDs` keeps its exact casing: the registered name forms the `/api/query/{name}` path Vidra
calls, and Vidra's default is that literal string.

**`python_transforms`** — add:

```yaml
  - name: cilium_manifest
    class_name: CiliumManifest
    file_path: "./transforms/cilium_manifest.py"
    # cilium_manifest.py imports the peering module from the shared src package, which falls
    # outside the closure Infrahub detects for it (the ./transforms directory holding its
    # file_path). Same reason as cabling_plan above.
    watch:
      files:
        - src/infrahub_solution_ai_dc/
```

The `watch:` entry is **required, not optional**. Infrahub's detected dependency closure for a Python
definition is the directory holding its `file_path` — here `./transforms`. The transform imports
`infrahub_solution_ai_dc.clusters`, which is outside that closure, so without this entry a change to
the peering module does not re-render the artifact. `cabling_plan` carries the same entry for the same
reason; `computed_interface_description` does not, because it imports only its sibling query model.

**`artifact_definitions`** — add:

```yaml
  - name: "cilium_bgp_manifest"
    artifact_name: "Cilium BGP Manifest"
    parameters:
      name: "name__value"
    content_type: "application/yaml"
    targets: "kubernetes_clusters"
    transformation: "cilium_manifest"
```

`artifact_name` is the published contract with Vidra (see `cilium-manifest-artifact.md`). The `name`
key is internal.

`content_type: "application/yaml"` is the first non-`text/plain`, non-`text/csv` artifact in the repo.

**Not changed**: `schemas`, `objects`, `menus`, `generator_definitions`, `jinja2_transforms`. In
particular **no `generator_definitions` entry is added** — there is no new generator (ADR-0002), and
`generate-server` is untouched.

## `objects/01_groups.yml` addition

```yaml
    # Target group for the Cilium BGP manifest artifact; NetworkKubernetesCluster objects join it.
    # Deliberately not parented under `devices` — a cluster is not a device and must never be
    # swept into the per-vendor startup-config artifacts.
    - name: kubernetes_clusters
```

## `schemas/kubernetes.yml` *(new file)*

Picked up automatically — `.infrahub.yml` registers the whole `schemas` directory, so no entry is
needed. See `data-model.md` §1.

## Seed data

**`objects/14_kubernetes.yml`** *(new)* — the demo cluster, numbered after `13_servers.yml` so it loads
last. Ordering is what matters: the cluster must exist before the services that reference it, so the
membership must be declared **from the service side** in `13_servers.yml`, or the cluster file must
come first.

Chosen approach: create the cluster in a **new `09_kubernetes.yml`** (before `10_fabric.yml`), and
declare membership on each service in `13_servers.yml` via the new `kubernetes_cluster` field. Rationale
— a cluster has no dependencies of its own, so it can be created early, and declaring membership on the
service keeps each member's cluster visible at the point the member is defined.

```yaml
# objects/09_kubernetes.yml
---
apiVersion: infrahub.app/v1
kind: Object
spec:
  kind: NetworkKubernetesCluster
  data:
    - name: "cilium-demo"
      description: "Demo Kubernetes cluster: mixed L3 (BGP-speaking) and L2 members across racks."
      member_of_groups: ["kubernetes_clusters"]
```

**`objects/13_servers.yml`** *(extends)* — retrofit the existing seeds as members and add enough to
demonstrate the multi-member and mixed cases (resolving the PRD's first open question):

| Service | Layer | Cluster | Rack | Purpose |
|---|---|---|---|---|
| `cilium-worker-1` *(existing)* | l3 | `cilium-demo` | `Rack-A2-2` | retrofitted; proves an existing seed joins without change to its other fields |
| `cilium-worker-2` *(new)* | l3 | `cilium-demo` | `Rack-A2-3` | second member → multi-member manifest (US1, N ≥ 2) |
| `cilium-worker-3` *(new)* | l3 | `cilium-demo` | `Rack-A3-1` | third member → matches US1's three-member acceptance scenario |
| `web-host-1` *(existing)* | l2 | `cilium-demo` | `Rack-A3-2` | retrofitted; the mixed L2/L3 case (US3) — present as a member, absent from the manifest |
| `green-cilium-worker-1` *(existing)* | l3 | *(none)* | `Rack-D2-1` | left unclustered; proves FR-001's "valid with none" |
| `green-web-host-1` *(existing)* | l2 | *(none)* | `Rack-D2-2` | left unclustered |

The three L3 members plus one L2 member make the manifest render **3 + 2 = 5** documents, which is
exactly the fixture `quickstart.md` verifies against.

### Placement is pinned, and must stay pinned

Every seeded service names an explicit `rack`, and **no two share one**. This is a deliberate
workaround, not a stylistic choice.

Leaving `rack` empty makes the `ServerGenerator` pick the least-utilized rack and the lowest-numbered
free `role: server` port on its leaf. Several services materializing together each read the same
"lowest free port" before any has claimed it, so they converge on the same port and collide. Until port
allocation goes through a resource pool, one server per rack keeps them on separate leaves where there
is nothing to contend for. Pinning also makes the members' distinct `peerAddress` values deterministic
rather than a side effect of whichever rack the generator happened to pick.

Two constraints bind any reassignment:

- **The rack's leaf template must end in `-compute`.** Those carry `profile-interface-server`
  (role `server`); the `-storage` templates carry `profile-interface-compute` (role `storage`) and have
  no server-role ports at all, so a service pinned there fails loud with no free port. That rules out
  `Rack-A2-4` and `Rack-A3-3` in Fabric-A, and `Rack-D3-3` and `Rack-D3-4` in Fabric-D. Note
  `rack_type` does **not** track this — `Rack-D2-4` is `rack_type: storage` but carries a compute
  template, so it is usable.
- **The rack must belong to the fabric behind the service's VRF** — Blue → Fabric-A (Pod-A2/Pod-A3),
  Green → Fabric-D (Pod-D2/Pod-D3) — or placement fails loud.

`Rack-A2-1` is deliberately left free: it is the rack the `blue-dmz` rack-scoped segment demo pins in
`objects/12_overlay.yml`.

## `triggers.yml`

**Not changed.** Artifacts re-render on their query's data dependency; only generators need trigger
rules. See `research.md` R7.

## Deferred: `protocols.py` regeneration

After `inv load-schema`, regenerate `src/infrahub_solution_ai_dc/protocols.py` against the running
stack. Until then it holds no `NetworkKubernetesCluster` and no `NetworkServer.node_selector`, and CI's
`mypy .` fails on any code referencing them. This gates task ordering — see `data-model.md`
§Migration.
