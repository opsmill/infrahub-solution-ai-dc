# Phase 1 Data Model: Multivendor Per-Vendor Configuration

No new schema nodes or attributes. This feature works entirely with **core groups**, **object templates**,
and **fabric/rack data**, plus a registration change. The "data model" here is the group hierarchy, the
template inventory delta, and the per-vendor fabric assignment.

## 1. Vendor device groups (`objects/01_groups.yml`)

All are `CoreStandardGroup`. Existing groups (`halls`, `racks`, `fabrics`, `pods`, `devices`, `tenants`)
are unchanged except that `devices` gains three children.

| Group | Kind | Parent | Members (populated by) |
|-------|------|--------|------------------------|
| `devices` | CoreStandardGroup | — | all devices (generators, existing behavior) |
| `cisco_devices` | CoreStandardGroup | `devices` | Cisco devices (generator, resolved from manufacturer) |
| `arista_devices` | CoreStandardGroup | `devices` | Arista devices (generator) |
| `dell_devices` | CoreStandardGroup | `devices` | Dell devices (generator) |

- **Membership rule**: a generated device joins `devices` **and** exactly one `{vendor}_devices` group.
- **Group name derivation**: `f"{manufacturer.name.lower()}_devices"`.
- **Validation**: manufacturer must resolve to one of {Cisco, Arista, Dell}; otherwise the generator raises
  (spec FR-004).

## 2. Object template inventory (`objects/06_device_template.yml`)

### Removed (5 — vendor-less)

`spine-switch`, `super-spine-switch`, `Generic Switch`, `leaf-switch-compute`, `leaf-switch-storage`.
(Referenced only by Fabric-A/B data today; orphaned once §4 re-vendoring lands.)

### Added (2 — storage leaves for the vendors that lacked them)

| Template | device_type | role | Port-profile split (mirror Dell storage leaf) |
|----------|-------------|------|-----------------------------------------------|
| `cisco-93400ld-h1-leaf-switch-storage` | `[Cisco, Nexus 93400LD-H1]` | leaf | spine-facing uplinks + compute-facing access |
| `arista-7050x4-48y-4df-leaf-switch-storage` | `[Arista, 7050X4-48Y-4DF]` | leaf | spine-facing uplinks + compute-facing access |

### Unchanged (full vendor sets after the change)

| Vendor | spine | super-spine | leaf-compute | leaf-storage |
|--------|-------|-------------|--------------|--------------|
| Dell | `dell-z9864f-on-spine-switch` | `dell-z9864f-on-super-spine-switch` | `dell-s5232f-on-leaf-switch-compute` | `dell-s5232f-on-leaf-switch-storage` |
| Cisco | `cisco-9364d-gx2-spine-switch` | `cisco-9364d-gx2-super-spine-switch` | `cisco-93400ld-h1-leaf-switch-compute` | **`cisco-93400ld-h1-leaf-switch-storage` (new)** |
| Arista | `arista-7060dx5-64s-spine-switch` | `arista-7060dx5-64s-super-spine-switch` | `arista-7050x4-48y-4df-leaf-switch-compute` | **`arista-7050x4-48y-4df-leaf-switch-storage` (new)** |

**Invariant (spec FR-005 / SC-005)**: after the change, every `template_name` carries a `device_type`.

## 3. Config templates & artifacts (`transforms/`, `.infrahub.yml`)

| Before | After |
|--------|-------|
| `templates/startup_config.j2` (1) | `startup_config_cisco.j2`, `startup_config_arista.j2`, `startup_config_dell.j2` (3, initially identical clones) |
| transform `device_startup_config` (1) | `cisco_device_startup_config`, `arista_device_startup_config`, `dell_device_startup_config` (3) |
| artifact `startup_configuration` → targets `devices` (1) | `cisco_startup_configuration` → `cisco_devices`, `arista_…` → `arista_devices`, `dell_…` → `dell_devices` (3) |
| query `network_device_startup_config` | unchanged (shared by all 3 transforms) |

See [contracts/infrahub-registration.md](./contracts/infrahub-registration.md).

## 4. Per-vendor fabric assignment (`objects/10_fabric.yml`, `objects/11_rack.yml`)

| Fabric | Today | Target | Super-spine template | Spine template | Leaf templates (compute / storage) |
|--------|-------|--------|----------------------|----------------|------------------------------------|
| Fabric-A | generic (vendor-less) | **Cisco** | `cisco-9364d-gx2-super-spine-switch` | `cisco-9364d-gx2-spine-switch` | `cisco-93400ld-h1-leaf-switch-compute` / `cisco-93400ld-h1-leaf-switch-storage` |
| Fabric-B | Dell | **Arista** | `arista-7060dx5-64s-super-spine-switch` | `arista-7060dx5-64s-spine-switch` | `arista-7050x4-48y-4df-leaf-switch-compute` / `arista-7050x4-48y-4df-leaf-switch-storage` |
| Fabric-C | — (new) | **Dell** | `dell-z9864f-on-super-spine-switch` | `dell-z9864f-on-spine-switch` | `dell-s5232f-on-leaf-switch-compute` / `dell-s5232f-on-leaf-switch-storage` |

- **Fabric-A**: 6 super-spines, Pods A1(role fabric)/A2/A3; racks under A2/A3 (2 storage racks:
  `Rack-A2-4`, `Rack-A3-3`) → now Cisco storage leaf.
- **Fabric-B**: 4 super-spines, Pods B1(role fabric)/B2/B3; racks under B2/B3 (2 storage racks:
  `Rack-B3-3`, `Rack-B3-4`) → now Arista storage leaf.
- **Fabric-C**: mirror of today's Fabric-B (4 super-spines, Pods C1/C2/C3, same rack layout) on Dell
  templates. Addressing/ASN auto-allocated by the fabric generator — no manual pool wiring.
- **`role: fabric` pods** (`Pod-A1/B1/C1`) reference no switch template → no vendor change.

## Entity relationships (unchanged, used here)

```text
NetworkFabric ─(super_spine_switch_template)→ TemplateNetworkDevice ─(device_type)→ NetworkDeviceType ─(manufacturer)→ OrganizationManufacturer
NetworkPod    ─(spine_switch_template)──────→ TemplateNetworkDevice ─(device_type)→ …
LocationRack  ─(leaf_switch_template)───────→ TemplateNetworkDevice ─(device_type)→ …
NetworkDevice ─(device_type)→ NetworkDeviceType ─(manufacturer)→ OrganizationManufacturer   # the resolution path
NetworkDevice ─(member_of_groups)→ CoreStandardGroup {devices, {vendor}_devices}
CoreStandardGroup{vendor_devices} ─(parent)→ CoreStandardGroup{devices}
```
