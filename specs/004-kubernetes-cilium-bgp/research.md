# Research: Kubernetes Clusters with Cilium BGP

**Feature**: `specs/004-kubernetes-cilium-bgp/`
**Date**: 2026-07-29
**Status**: Complete — no NEEDS CLARIFICATION remaining

This document records what was **verified against primary sources** (the Cilium documentation source
tree and the Vidra operator source tree) rather than assumed. The PRD's "Implementation Decisions"
and "Testing Decisions" sections are already agreed and were not re-litigated; research here exists
to (a) pin the exact external contract shapes the feature must emit, and (b) correct two factual
claims inherited from the PRD.

---

## R1 — Cilium v2 BGP resource shapes

**Decision**: Emit three kinds under `apiVersion: cilium.io/v2` — `CiliumBGPClusterConfig` (one per
eligible L3 member), `CiliumBGPPeerConfig` (one, shared), `CiliumBGPAdvertisement` (one, shared).

**Source**: `cilium/cilium` → `Documentation/network/bgp-control-plane/bgp-control-plane-configuration.rst`,
fetched at HEAD via the GitHub contents API. (The rendered docs site returned HTTP 429; the docs
*source* is the same content and is authoritative.)

**Verified field shapes** — reproduced from the documentation's own examples:

```yaml
apiVersion: cilium.io/v2
kind: CiliumBGPClusterConfig
metadata:
  name: cilium-bgp
spec:
  nodeSelector:
    matchLabels:
      rack: rack0
  bgpInstances:
  - name: "instance-65000"
    localASN: 65000
    localPort: 179
    peers:
    - name: "peer-65000-tor1"
      peerASN: 65000
      peerAddress: fd00:10:0:0::1
      peerConfigRef:
        name: "cilium-peer"
```

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
          advertise: "bgp"
```

```yaml
apiVersion: cilium.io/v2
kind: CiliumBGPAdvertisement
metadata:
  name: bgp-advertisements
  labels:
    advertise: bgp
spec:
  advertisements:
    - advertisementType: "PodCIDR"
```

**Notes carried into the design**:

- `peerConfigRef.group` and `peerConfigRef.kind` are **optional**, defaulting to `cilium.io` and
  `CiliumBGPPeerConfig`. We omit both — fewer fields to keep correct, and the defaults are exactly
  what we want.
- `localPort` is **optional**. Omitting it is deliberate: without it Cilium instantiates the router
  with no listening port, so it only *initiates* connections. Setting `179` would require granting
  `CAP_NET_BIND_SERVICE` via a Helm value, which is cluster-side configuration this feature does not
  own. The leaf initiates or accepts either way, so peering still comes up.
- The linkage between peer config and advertisement is a **label selector**, not a name reference:
  `CiliumBGPPeerConfig.spec.families[].advertisements.matchLabels` must match labels on the
  `CiliumBGPAdvertisement` metadata. Both sides of that selector are ours to choose and must agree
  inside the single rendered manifest.
- `timers`, `authSecretRef`, `ebgpMultihop`, `gracefulRestart`, `transport` are all optional on
  `CiliumBGPPeerConfig` and are omitted — the spec puts them out of scope, and the source of truth
  holds no data for them.

**Alternatives considered**:

- *One shared `CiliumBGPClusterConfig` plus one `CiliumBGPNodeConfigOverride` per member.* **Rejected,
  and now verified rather than assumed.** `CiliumBGPNodeConfigOverride` can override `localASN`,
  `peers[*].localAddress`, `localPort` and `routerID` — but there is **no `peerAddress` field on it**.
  The docs are explicit that the peering source interface "are based on a route lookup of the peer
  address defined in `CiliumBGPClusterConfig`". Since every member peers with a *different* leaf on a
  *different* /31, and peer address is only expressible in the cluster config, one cluster config per
  member is the only shape that works. This confirms the PRD's assumption for the right reason.
- *`cilium.io/v2alpha1` with the older `CiliumBGPPeeringPolicy`.* Rejected — superseded, and the v2
  resource set is what current Cilium documents.

---

## R2 — How Vidra consumes the artifact

**Decision**: Register the artifact-identity query under the name **`ArtifactIDs`** with a single
variable named **`artifactname`**, returning `id`, `storage_id { id }`, `checksum { value }` and
`name { value }` from `CoreArtifact`. Pin the artifact name as a published contract.

**Source**: `infrahub-operator/vidra` at HEAD — `api/v1alpha1/infrahubsync_types.go`,
`internal/adapter/infrahub/client.go`, `internal/controller/infrahubsync_controller.go`,
`docs/docs/guides/infrahub.md`, `config/samples/infrahub_v1alpha1_infrahubsync.yaml`.

**Verified mechanics**:

- Vidra's `InfrahubSync` CR (`infrahub.operators.com/v1alpha1`, cluster-scoped) selects the artifact
  by **name**, via `spec.source.artefactName` — note Vidra's JSON key uses the spelling
  `artefactName` even though the Go field is `ArtifactName`. This is the concrete reason the artifact
  name is a contract: it is typed into a CR that lives in the cluster.
- The controller calls `RunQuery` against `POST {infrahubAPIURL}/api/query/{queryName}` with query
  params `update_group=false`, `branch={targetBranch}`, `at={targetDate}`, and a JSON body of
  `{"variables": {"artifactname": "<artifact name>"}}`.
- `queryName` defaults to the literal **`ArtifactIDs`** (`defaultQueryName` in
  `infrahubsync_controller.go`) and is only overridable through a ConfigMap key `queryName`. Naming
  our query `ArtifactIDs` therefore makes it work against a default Vidra install with no extra
  configuration.
- The exact query Vidra's own guide instructs users to add to Infrahub:

  ```graphql
  query ArtifactIDs($artifactname: [String]) {
    CoreArtifact(name__values: $artifactname) {
      edges {
        node {
          id
          storage_id {
            id
          }
          checksum {
            value
          }
          name {
            value
          }
        }
      }
    }
  }
  ```

  Note `$artifactname` is a **list** type (`[String]`) matched with `name__values` (plural), not
  `name__value`. Getting this wrong is a silent no-match rather than an error.
- `InfrahubSyncStatus.Checksums []string` is how Vidra remembers what it last synced; it re-downloads
  only when the checksum changes. This satisfies FR-008 / user story 12 exactly as written.
- Vidra's own example artifact is a **multi-document** YAML template (`---`-separated Namespace,
  Deployment, Service, Ingress). Multi-document YAML in one artifact is the shape Vidra expects, which
  is what lets a single cluster artifact carry N cluster configs plus the two shared documents.

**Rejected**: one artifact per member. A deleted artifact conveys nothing to Vidra — an
`InfrahubSync` points at one artifact name, so a removed member would leave its `InfrahubSync`
dangling and its peering un-withdrawn. The spec's single-artifact-per-cluster packaging is what makes
member removal reconcile correctly.

---

## R3 — Where the manifest's four values come from

**Decision**: Read `localASN` and `peerASN` from the **server-side** stored BGP session, and
`peerAddress` by walking the member's cabling to the leaf port's IP.

**Source**: `generators/generate_server.py:690-695`, `src/infrahub_solution_ai_dc/servers.py`,
`schemas/routing.yml`, `transforms/templates/startup_config_arista.j2:105-124`.

**Verified**: `NetworkBGPSession` stores `local_as`, `remote_as`, `address_family`, `rr_client`,
`device`, `peer_device` — and **no IP addresses at all**. The generator upserts the pair as:

```python
upsert_ebgp_session(device=leaf,   peer=server, local_as=overlay_asn, remote_as=server_asn)
upsert_ebgp_session(device=server, peer=leaf,   local_as=server_asn,  remote_as=overlay_asn)
```

So on the **server-side** session (`device == server`), `local_as` *is* the member's own ASN and
`remote_as` *is* its leaf's local AS. That single object yields both `localASN` and `peerASN` with no
arithmetic and no cross-referencing — and it is the same object the leaf's startup config renders the
other half of, which is precisely the "one source, cannot disagree" property SC-002 asserts.

`peerAddress` cannot come from the session. The existing leaf templates solve the mirror-image problem
by walking `session.peer_device.node.interfaces` and taking the first interface with an IP — which
works there only because the peer is a *server* with one interface. Walking the leaf's interfaces the
same way would be wrong: a leaf has many, and only one faces this member. The correct path is the
cabling:

```text
member service → server → interfaces → link → endpoints → (the NetworkInterface end) → ip_address
```

This is the leaf's /31 address, and it follows a move automatically because the link is what moves.

**Consequence for eligibility (FR-004)**: "lacking a complete session or leaf address" becomes
concrete and checkable — a member is ineligible when any of `layer == "l3"`, a server-side
`ipv4_unicast` session, `local_as`, `remote_as`, or a resolvable cabled leaf-port IP is missing.

---

## R4 — Node selector derivation

**Decision**: A `read_only` Jinja2 `computed_attribute` on `NetworkServer`, template
`{{ hostname__value | replace("server-", "", 1) }}`, rendered into `nodeSelector.matchLabels` under
the key `infrahub.io/server`.

**Source**: `generators/generate_server.py:52-54` (`return f"server-{service_name}"`),
`schemas/device.yml:203-209` (the existing computed-attribute precedent),
`tests/unit/test_computed_attribute.py` (the existing test precedent using
`infrahub_sdk.template.Jinja2Template`).

**Verified**: server hostnames are `server-{service_name}` and `NetworkServerService.name` is
`unique: true`, so stripping the prefix yields a value that is unique by construction — which is what
makes the spec's "node selector collision: impossible" edge case true rather than hopeful.

Using `replace(..., 1)` (count-limited) rather than an unanchored replace matters: a service named
`server-side-cache` would otherwise have its *inner* occurrence mangled too. Anchoring to the first
occurrence only is the faithful reading of "with the `server-` prefix removed".

**Alternatives considered**: computing it in the transform. Rejected — FR-002 requires the value be
*exposed* on the Server ("Every Server MUST expose a read-only node selector value"), because the
operator has to read it to label their nodes. A transform-local variable is not exposed anywhere.

---

## R5 — Transform type: Python, not Jinja2

**Decision**: A Python `InfrahubTransform` (`transforms/cilium_manifest.py`) that renders YAML via
`yaml.safe_dump_all`, paired with a pure peering module in `src/`.

**Rationale**: The four per-vendor startup configs are Jinja2 because device config is
whitespace-significant free text. A Kubernetes manifest is *structured data*, and the spec's tests
assert on "document count and field values" after parsing — not on rendered text. Building Python
dicts and serialising them means the emitted YAML is valid by construction, and the unit tests parse
the same structure they assert on. `yaml` is already an installed transitive dependency of the
Infrahub SDK, so this adds no new dependency (matching the PRD's "New dependency — none" gate).

Jinja2 was considered and rejected: hand-indented YAML in a template is exactly where an empty-list
case (FR-005, the all-L2 cluster) silently emits a malformed document.

**Repo pattern to follow**: `transforms/cabling_plan.py` — an `InfrahubTransform` subclass with a
`query = "<query name>"` class attribute, an `async def transform(self, data)`, and a generated
sibling `*_query.py` Pydantic model. It also demonstrates the `.infrahub.yml` `watch:` entry that a
transform importing from `src/infrahub_solution_ai_dc/` **requires** — without it, a change under
`src/` does not re-run the transform, because Infrahub's detected dependency closure is only the
directory holding `file_path`. Our transform imports the peering module, so it needs that entry.

---

## R6 — Two PRD claims corrected

Both were checked against the repository rather than taken forward.

**(a) "the stale generated-definitions check fails until regeneration" — inaccurate.**
`.github/workflows/ci.yml` has no generated-definitions staleness check. Its jobs are
`python-lint` (`ruff format --check`, `ruff check`, `mypy .`), `yaml-lint`, `markdown-lint`,
`integration-test`, `documentation`, and `validate-documentation-style`.

The real gate is **`mypy .`**: `src/infrahub_solution_ai_dc/protocols.py` is generated from the live
schema, so until it is regenerated it holds no `NetworkKubernetesCluster` and no `node_selector` on
`NetworkServer`. Any code importing or attribute-accessing those fails type-checking. This is a
sharper constraint than the PRD implied, and it dictates task ordering: schema changes and the
`protocols.py` regeneration must land before the transform that consumes them, or CI is red in a way
no amount of test-writing fixes.

**(b) "the Server service's integration suite is still skipped" — accurate, verified.**
Every test in `tests/integration/test_server_service.py` carries `@pytest.mark.skip`, as does
`test_overlay_daytwo.py:88`. So the PRD's decision to add **no** integration tests here stands: doing
otherwise would add skipped tests, not coverage. Note that CI's `integration-test` job *does* build a
real Infrahub image and run `pytest tests/` — the suite is skipped by marker, not absent for lack of a
stack. Recording this so a future reader does not mistake the deferral for a missing capability.

---

## R7 — Trigger / re-render mechanism (FR-006)

**Decision**: Rely on the artifact's own data dependency; add no trigger rule.

**Rationale**: An artifact definition re-renders when the data its query traverses changes. Because
the cluster artifact's query walks cluster → member services → server → session and cabling, adding a
member, removing one, or moving one to another port all fall inside that traversal and re-render it
without further wiring. `triggers.yml` exists for the *generator* cascade (a generator must be told to
re-run); artifacts are pull-based on their query. This is also what keeps SC-003 true — the physical
topology cascade is not in the traversal, so it does not re-run.

**Consequence**: no `triggers.yml` change is in scope, and FR-006's verification is therefore a
fixture-differencing unit test (render N vs N+1 vs moved) rather than a live trigger assertion — which
is exactly what the PRD's Testing Decisions prescribe.
