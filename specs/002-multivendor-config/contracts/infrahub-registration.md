# Contract: `.infrahub.yml` Registration (per-vendor config)

Replace the single startup-config transform + artifact with three of each, one per vendor group. The GraphQL
query is unchanged and shared.

## `queries` — unchanged

`network_device_startup_config` → `./transforms/startup_config.gql` stays as-is (all three transforms use it).

## `jinja2_transforms` — replace 1 with 3

Remove:

```yaml
- name: device_startup_config
  query: network_device_startup_config
  template_path: "./transforms/templates/startup_config.j2"
```

Add:

```yaml
- name: cisco_device_startup_config
  description: "Cisco device config transform"
  query: network_device_startup_config
  template_path: "./transforms/templates/startup_config_cisco.j2"
- name: arista_device_startup_config
  description: "Arista device config transform"
  query: network_device_startup_config
  template_path: "./transforms/templates/startup_config_arista.j2"
- name: dell_device_startup_config
  description: "Dell device config transform"
  query: network_device_startup_config
  template_path: "./transforms/templates/startup_config_dell.j2"
```

## `artifact_definitions` — replace 1 with 3

Remove the `startup_configuration` definition (targets `devices`). Add three, each targeting a vendor group:

```yaml
- name: "cisco_startup_configuration"
  artifact_name: "Startup configuration"
  parameters: { name: "hostname__value" }
  content_type: "text/plain"
  targets: "cisco_devices"
  transformation: "cisco_device_startup_config"
- name: "arista_startup_configuration"
  artifact_name: "Startup configuration"
  parameters: { name: "hostname__value" }
  content_type: "text/plain"
  targets: "arista_devices"
  transformation: "arista_device_startup_config"
- name: "dell_startup_configuration"
  artifact_name: "Startup configuration"
  parameters: { name: "hostname__value" }
  content_type: "text/plain"
  targets: "dell_devices"
  transformation: "dell_device_startup_config"
```

The `cabling_plan` artifact/transform and `computed_interface_description` transform are **unchanged**.

## Invariants

- No artifact definition targets `devices` → each device (in `devices` + one vendor group) renders exactly
  one startup config (spec SC-002).
- `targets` values equal the group names from [vendor-groups.md](./vendor-groups.md) exactly.
- Templates start as identical clones of the removed `startup_config.j2`; divergence is later work.
