# Contract: `.infrahub.yml` Registration & Triggers

How the Server service/generator register with the Infrahub platform. Mirror the existing tenant
generator/query/trigger entries in `.infrahub.yml`, `objects/01_groups.yml`, and `triggers.yml`.

## `.infrahub.yml` additions

**queries** — add:

- `generate_server` → `generators/generate_server.gql`

(The existing `network_device_startup_config` query is unchanged as an entry; its `.gql` content is expanded
per the GraphQL contract.)

**generator_definitions** — add (exactly the tenant shape):

```yaml
- name: generate-server
  file_path: "./generators/generate_server.py"       # class ServerGenerator
  query: generate_server
  targets: server_services                           # CoreStandardGroup of NetworkServerService objects
  parameters:
    name: name__value                                # NetworkServerService.name → $name
  class_name: ServerGenerator
  convert_query_response: false
  execute_in_proposed_change: false
  execute_after_merge: false
```

**jinja2_transforms / artifact_definitions** — **unchanged**. The existing per-vendor
`{vendor}_device_startup_config` transforms and `Startup configuration` artifacts (targets:
`{vendor}_devices`) are reused; only the expanded template + query emit the server interface/eBGP config on
leaves. **No new artifact** — and crucially no artifact targets `NetworkServer`.

## Groups (`objects/01_groups.yml`)

- Add a `server_services` `CoreStandardGroup` (parallels `tenants`/`racks`/`pods`/…) so the
  generator_definition has a target group; new `NetworkServerService` objects join it
  (`member_of_groups: [server_services]`).
- **Do not** add any group for `NetworkServer`. It must never join `devices` or `{vendor}_devices`.

## Pools (`objects/07_pools.yml`, `objects/04_ipam.yml`)

- `07_pools.yml` — add a global `CoreNumberPool`:

  ```yaml
  - name: "Server ASN Pool"
    node: NetworkServer
    node_attribute: asn
    start_range: 4200000000
    end_range: 4294967294
  ```

- `04_ipam.yml` — seed a `server_p2p` supernet prefix that `PodGenerator` carves per-Pod into each pod's
  `server_prefix_pool` (a `CoreIPPrefixPool`), mirroring how the existing pod pools are derived.

## Trigger (`triggers.yml`)

Add, mirroring the tenant trigger:

- `CoreGeneratorAction` (`data:` list): `{name: run-server-generator, generator: generate-server}`.
- `CoreNodeTriggerRule`:

  ```yaml
  - name: trigger-server-generator-update-checksum
    branch_scope: "other_branches"
    node_kind: NetworkServerService
    mutation_action: "updated"
    action: run-server-generator
    matches:
      kind: CoreNodeTriggerAttributeMatch
      data:
        - attribute_name: checksum
          value_match: any
  ```

(Optionally also a `created` rule if first-create should trigger without a checksum bump — match the tenant
convention chosen in `triggers.yml`.)

## Idempotency / loop-prevention contract

- The ServerGenerator writes a session + cabling onto the **leaf** device and (L2) mutates
  `NetworkSegment.racks`. The Rack/Pod generators' `GeneratorMixin` checksums **must exclude** these
  server/overlay relationships so the write does not re-trigger the physical cascade (ADR-0004 caveat).
- `NetworkServer.asn` allocation is guarded ("allocate only if unset") and excluded from any self-retrigger
  path. Sessions upsert by `"{a}__{b}"` name; the /31 allocates by a stable `identifier`; placement uses
  edge-scoped `add_relationships`. Re-run ⇒ empty diff (SC-003).
