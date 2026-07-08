# Contract: Vendor Device Groups (`objects/01_groups.yml`)

Add three `CoreStandardGroup`s as children of the existing `devices` group. No schema change — nesting uses
the core `CoreGroup.parent`/`children` relationship.

## Additions

The existing file lists groups under `spec.data`. Add three entries, each referencing `devices` as parent
(mirror whatever parent/child expression the object loader accepts — see plan "Items to verify"):

```yaml
# objects/01_groups.yml (illustrative — final syntax per loader)
spec:
  kind: CoreStandardGroup
  data:
    - name: halls
    - name: racks
    - name: fabrics
    - name: pods
    - name: devices
    - name: tenants
    - name: cisco_devices
      parent: devices
    - name: arista_devices
      parent: devices
    - name: dell_devices
      parent: devices
```

Fallback expression if `parent:` on the child is not accepted by the loader: set `children` on the `devices`
entry instead (`children: [cisco_devices, arista_devices, dell_devices]`). Both resolve to the same
`CoreGroup` relationship.

## Membership contract

- Membership of the three child groups is **not** authored here — it is stamped by the generators (see
  [vendor-resolution.md](./vendor-resolution.md)).
- `devices` continues to receive every device (existing generator behavior). Each device additionally joins
  exactly one vendor child group.

## Invariants

- Each `{vendor}_devices` group's `parent` is `devices`.
- Group names are exactly `cisco_devices`, `arista_devices`, `dell_devices` (must match
  `f"{manufacturer.name.lower()}_devices"` used by the generator and the artifact `targets`).
