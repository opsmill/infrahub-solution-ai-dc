# Contract: `.infrahub.yml` Registration & Triggers

How the new overlay artifacts register with the Infrahub platform. Mirror the existing
generator/query/trigger entries already in `.infrahub.yml` and `objects/20_triggers.yml(.save)`.

## `.infrahub.yml` additions

**queries** — add:

- `generate_tenant` → `generators/generate_tenant.gql`

(The existing `network_device_startup_config` query entry is unchanged; its `.gql` file content is expanded
per the GraphQL contract.)

**generator_definitions** — add:

```text
- name: generate-tenant
  file_path: generators/generate_tenant.py        # class OverlayGenerator
  query: generate_tenant
  targets: tenants                                 # CoreStandardGroup of NetworkTenant objects
  parameters:
    name: name__value                              # NetworkTenant.name → $name
```

**jinja2_transforms / artifact_definitions** — unchanged. The existing `device_startup_config` transform and
`startup_configuration` artifact (targets: devices) are reused; expanded template + query now emit overlay
config. No new artifact is introduced.

## Groups (`objects/01_groups.yml`)

- Add a `tenants` `CoreStandardGroup` (parallels the existing halls/racks/fabrics/pods/devices groups) so the
  generator_definition has a target group; new `NetworkTenant` objects join it.

## Trigger (`objects/20_triggers.yml(.save)`)

Add, mirroring the existing pod/rack trigger pattern:

- `CoreGeneratorAction`: `run-tenant-generator` → `generate-tenant`.
- `CoreNodeTriggerRule`: fires on `NetworkTenant` mutations (checksum + relevant attributes/relationships:
  vrfs, segments, placement) → `run-tenant-generator`.

## Idempotency / loop-prevention contract

- OverlayGenerator writes `Device.segments` on leafs. The Rack/Pod generators' `GeneratorMixin` checksums
  **must exclude** overlay relationships so this write does not re-trigger the physical cascade (D12 caveat).
- `overlay_asn` allocation in the FabricGenerator must be guarded ("allocate only if unset") and excluded
  from the fabric checksum (research.md open item 1).
