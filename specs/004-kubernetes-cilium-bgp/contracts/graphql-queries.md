# Contract: GraphQL Queries

Two new queries. One feeds the Cilium manifest transform; one is Vidra's polling contract. Existing
`transforms/*.gql` are the style reference; the `*_query.py` Pydantic models follow the repo convention
(`_Value*` leaf models, `_`-prefixed privates, `Field(alias=...)`), with `convert_query_response: false`.

---

## 1. `transforms/cilium_manifest.gql` *(new)* — transform input

**Input variable**: `$name: String!` — the `NetworkKubernetesCluster.name`, per the artifact
definition's `parameters: {name: name__value}`.

**Must return** every value the peering records need, plus enough to apply eligibility:

```text
NetworkKubernetesCluster(name__value: $name)
  edges { node {
    id
    name { value }
    members { edges { node {
      id
      name { value }
      layer { value }                                  # l2 | l3 — eligibility check 1
      server { node {
        id
        hostname { value }
        node_selector { value }                        # computed; the nodeSelector value
        asn { value }
        bgp_sessions { edges { node {                  # server-side sessions only, by construction
          address_family { value }                     # must be ipv4_unicast
          local_as { value }                           # -> localASN
          remote_as { value }                          # -> peerASN
        } } }
        interfaces { edges { node {                    # the cabling path to the leaf's /31
          id
          name { value }                               # REQUIRED: deterministic interface ordering sorts on it
          link { node {
            id
            endpoints { edges { node {
              id
              __typename                               # discriminate ServerInterface vs NetworkInterface
              ... on NetworkInterface {
                ip_address { node {
                  id                                   # REQUIRED: a null relationship id is how "unset" is detected
                  address { value }                    # -> peerAddress (strip /31)
                } }
              }
            } } }
          } }
        } } }
      } }
    } } }
  } }
```

### Notes that matter

- **`bgp_sessions` on a `NetworkServer` are already server-side only.** The relationship identifier is
  `device__bgp_session`, i.e. sessions whose `device` *is* this server. The leaf's mirror session hangs
  off the leaf. So no direction filtering is needed in the query — but the transform must still filter
  on `address_family == "ipv4_unicast"`, since the relationship does not constrain family.
- **`endpoints` returns both ends of the link**, including the member's own `ServerInterface`. The
  transform must select the `NetworkInterface` end (the leaf port) — hence `__typename` and the
  inline fragment. Selecting the wrong end yields the *server's* address, which would be a
  plausible-looking but wrong `peerAddress`.
- **`address.value` carries the prefix length** (`10.0.0.1/31`). Strip it; Cilium wants a bare address.
- A member whose `server` is null (mid-provisioning) must not break the query — `server` is an optional
  to-one, so it returns `node: null` and the transform treats it as ineligible.
- **`id` must be selected at every node level, and `name` on the server's interfaces.** Both were
  missing from an earlier draft of this contract and each would have silently dropped *every* member
  (found while implementing T017/T018):
  - `id` is how "is this relationship set" is tested — the same non-null-`id` check `servers.py` uses.
    A node selected without `id` reads as unset, so the member is treated as incomplete and omitted.
  - `name` on `interfaces` is what deterministic interface ordering sorts on. Without it there is
    nothing to sort by, and the ordering guarantee that keeps the artifact checksum stable is lost.

  Both failure modes are silent — a smaller manifest, not an error — which is precisely why they are
  called out here rather than left to be rediscovered.

**Registration**: `.infrahub.yml` → `queries:` as `cilium_manifest`.

---

## 2. `ArtifactIDs` *(new)* — Vidra's polling contract

**File**: `queries/artifact_ids.gql` *(new directory — no existing query lives outside
`generators/`/`transforms/`, and this one belongs to neither)*

**The query name, the variable name, and the field set are all fixed by Vidra.** This is not a place to
exercise judgment:

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

| Constraint | Value | Consequence of getting it wrong |
|---|---|---|
| Query name | `ArtifactIDs` | Vidra's `defaultQueryName` is the literal `ArtifactIDs`. A different name requires every consumer to set a `queryName` ConfigMap key. |
| Variable name | `artifactname` | Vidra POSTs `{"variables": {"artifactname": ...}}`. A mismatch means no variable binding. |
| Variable type | `[String]` (a **list**) | Paired with `name__values` (plural). Using `String` + `name__value` silently returns nothing rather than erroring. |
| Fields | `id`, `storage_id { id }`, `checksum { value }`, `name { value }` | Vidra reads all four; `checksum` drives its re-sync decision. |

### ⚠️ `storage_id { id }` is correct — do not "fix" it to `{ value }`

It looks wrong. It is not. Both halves were verified:

- **Infrahub 1.11 introspection**: `CoreArtifact.storage_id` is a `TextAttribute`, and `TextAttribute`
  exposes **both** `id` and `value`. So `{ id }` is valid, and returns the attribute node's UUID rather
  than the storage-id string.
- **Vidra's unmarshalling** (`internal/adapter/infrahub/models.go`):

  ```go
  StorageID struct {
      ID string `json:"id"`
  } `json:"storage_id"`
  ```

  assigned as `StorageID: node.StorageID.ID`.

So `{ id }` is precisely what Vidra parses. Changing it to `{ value }` would make Vidra unmarshal an
empty `StorageID` — **with no error**, since the JSON key would simply be absent. Every deployed
consumer would break silently.

This is recorded because `{ value }` is the intuitive reading and a future reader, reviewer, or linter
is likely to "correct" it.

Vidra invokes it as `POST {infrahubAPIURL}/api/query/ArtifactIDs?update_group=false&branch=<branch>&at=<date>`.

This query is **not** artifact- or cluster-specific — it matches any artifact by name and serves every
Vidra consumer in the deployment. It is registered once.

**Registration**: `.infrahub.yml` → `queries:` as `ArtifactIDs`. The registered name must match the
query name in the document, since that is what forms the `/api/query/{name}` path.

**Verification**: FR-008's check ("the query is registered and returns those three fields") is
inherently live — it needs a running stack. Per the PRD's Testing Decisions there is no integration
test here, so verification is the manual `curl` in `quickstart.md`. What *can* be checked statically,
and should be, is that the registered name and the in-document query name agree and that the four
fields are present.
