# Phase 1 Data Model: Juniper / Junos Vendor Support

Every entity below is an **instance of an existing kind**. No new node kinds, no new attributes, no new
relationships — see [research.md](./research.md) "Cross-cutting: what does not change".

## 1. Vendor group — `objects/01_groups.yml`

One addition, alongside the three existing vendor groups:

```yaml
    - name: juniper_devices
      parent: devices
```

Membership is **not** declared here. It is stamped at device-creation time by the generators via
`member_of_groups=["devices", self.vendor_group]`, where `vendor_group` is resolved from the device
template's manufacturer. Group name derivation: `f"{manufacturer.name.strip().lower()}_devices"`.

## 2. Manufacturer — `objects/02_manufacturer.yml`

```yaml
    - name: Juniper
```

Case is display-only; resolution lowercases before matching `SUPPORTED_VENDORS`.

## 3. Device types — `objects/03_device_type.yml`

Two SKUs, matching the two-models-per-vendor pattern:

```yaml
    - name: "QFX5230-64CD"
      manufacturer: ["Juniper"]
    - name: "QFX5120-48Y-8C"
      manufacturer: ["Juniper"]
```

| Model | Role | Ports |
|---|---|---|
| QFX5230-64CD | spine + super-spine | 64× 400G QSFP56-DD |
| QFX5120-48Y-8C | leaf (compute + storage) | 48× 10/25G SFP28 + 8× 100G QSFP28 |

`manufacturer` is given as a single-element list because `NetworkDeviceType`'s human-friendly ID is
`[manufacturer__name__value, name__value]` (`schemas/device.yml:40-42`).

## 4. Device templates — `objects/06_device_template.yml`

Four `TemplateNetworkDevice` entries, appended to the existing twelve. All reuse the **existing
vendor-neutral interface profiles** from `objects/05_profiles.yml` — no new profiles.

Port-role split follows the established convention exactly: super-spines face spines; spines split
lower-half-to-leaf / upper-half-to-super-spine; leaves split access-ports / spine-facing uplinks; every
template declares exactly one `Loopback0` with `role: "loopback"` and no profile.

| Template name | Role | Device type | Interfaces → profile |
|---|---|---|---|
| `juniper-qfx5230-64cd-super-spine-switch` | `super_spine` | QFX5230-64CD | `Loopback0` (role `loopback`)<br>`et-0/0/[0-63]` → `profile-interface-spine` |
| `juniper-qfx5230-64cd-spine-switch` | `spine` | QFX5230-64CD | `Loopback0` (role `loopback`)<br>`et-0/0/[0-31]` → `profile-interface-leaf`<br>`et-0/0/[32-63]` → `profile-interface-super-spine` |
| `juniper-qfx5120-48y-8c-leaf-switch-compute` | `leaf` | QFX5120-48Y-8C | `Loopback0` (role `loopback`)<br>`xe-0/0/[0-47]` → `profile-interface-server`<br>`et-0/0/[48-55]` → `profile-interface-spine` |
| `juniper-qfx5120-48y-8c-leaf-switch-storage` | `leaf` | QFX5120-48Y-8C | `Loopback0` (role `loopback`)<br>`xe-0/0/[0-47]` → `profile-interface-compute`<br>`et-0/0/[48-55]` → `profile-interface-spine` |

Note `profile-interface-compute` carries `role: "storage"` and MTU 9000 (`objects/05_profiles.yml:10-12`) —
the naming is pre-existing and slightly confusing, but the storage leaf uses it exactly as the Dell, Cisco and
Arista storage leaves do.

**Shape**, mirroring the existing entries (`parameters: expand_range: true` on both the device-template spec
and each nested interface block):

```yaml
    # Juniper QFX5230-64CD (64x 400G QSFP56-DD) — spine & super-spine
    - template_name: "juniper-qfx5230-64cd-spine-switch"
      device_type: ["Juniper", "QFX5230-64CD"]
      role: "spine"
      interfaces:
        kind: TemplateNetworkInterface
        parameters:
          expand_range: true
        data:
          - template_name: "JuniperQFX5230SpineSwitchLoopback0"
            name: "Loopback0"
            role: "loopback"
          - template_name: "JuniperQFX5230SpineSwitchet-0/0/[0-31]"
            name: "et-0/0/[0-31]"
            profiles: ["profile-interface-leaf"]
          - template_name: "JuniperQFX5230SpineSwitchet-0/0/[32-63]"
            name: "et-0/0/[32-63]"
            profiles: ["profile-interface-super-spine"]
```

Interface `template_name` follows the existing PascalCase-no-separator convention with the interface name
embedded verbatim (so the Junos name appears lowercase inside it, as
`JuniperQFX5230SpineSwitchet-0/0/[0-31]`). These names only need to be globally unique.

**Range expansion is verified** for all four Junos forms — see [research.md](./research.md) D3.

### Loopbacks

Each template declares only `Loopback0`. The **second** loopback, `Loopback1` (role `vtep`), is created
imperatively at `src/infrahub_solution_ai_dc/addressing.py:82-90` for leaves only, with the name defaulting
at `:64`. Both keep their vendor-neutral names in the data model and are rendered as `lo0` unit 0 / unit 1 by
the Junos template — see [research.md](./research.md) D4 and
[contracts/junos-config-contract.md](./contracts/junos-config-contract.md).

## 5. Fabric — `objects/10_fabric.yml`

Fabric-D mirrors Fabric-B/C's **topology** exactly. `amount_of_spines` is not set (defaults to 4), matching B
and C. It deliberately diverges from them in one respect only — it gets its own overlay tenant (see §7).

```yaml
    # Fabric-D — Juniper (mirrors Fabric-B/C's topology with the Juniper templates).
    - name: "Fabric-D"
      index: 4
      member_of_groups: ["fabrics"]
      super_spine_switch_template: "juniper-qfx5230-64cd-super-spine-switch"
      amount_of_super_spines: 4
      children:
        kind: NetworkPod
        data:
          - name: "Pod-D1"
            index: 1
            role: "fabric"
            member_of_groups: ["pods"]
          - name: "Pod-D2"
            index: 2
            spine_switch_template: "juniper-qfx5230-64cd-spine-switch"
            member_of_groups: ["pods"]
          - name: "Pod-D3"
            index: 3
            spine_switch_template: "juniper-qfx5230-64cd-spine-switch"
            member_of_groups: ["pods"]
```

`Pod-D1` carries `role: "fabric"` and gets **no** spine template — it is the super-spine pod. Addressing and
the overlay ASN are allocated automatically per fabric (research.md D8), so no manual IPAM entries are needed.

## 6. Racks — `objects/11_rack.yml`

Eight racks, mirroring the Fabric-B block (`objects/11_rack.yml:80-143`) with the Juniper leaf templates. All
live in the existing `Hall-A1`.

| Rack | Index | `rack_type` | Pod | `amount_of_leafs` | Leaf template |
|---|---|---|---|---|---|
| Rack-D2-1 | 1 | compute | Pod-D2 | 2 | compute |
| Rack-D2-2 | 2 | compute | Pod-D2 | 1 | compute |
| Rack-D2-3 | 3 | compute | Pod-D2 | 2 | compute |
| Rack-D2-4 | 4 | storage | Pod-D2 | 1 | compute |
| Rack-D3-1 | 1 | compute | Pod-D3 | 2 | compute |
| Rack-D3-2 | 2 | compute | Pod-D3 | 1 | compute |
| Rack-D3-3 | 3 | storage | Pod-D3 | 1 | storage |
| Rack-D3-4 | 4 | compute | Pod-D3 | 1 | storage |

> **Mirror faithfully, including the quirks.** Fabric-B and Fabric-C both have two rows where `rack_type` and
> the chosen leaf template disagree — `Rack-x2-4` is `storage` but uses the *compute* template, and
> `Rack-x3-4` is `compute` but uses the *storage* template. This is pre-existing in both fabrics. Fabric-D
> reproduces it so the four fabrics stay directly comparable; "fixing" it here would make Fabric-D the odd
> one out and is out of scope.

Total: 11 leaves, matching Fabric-A/B/C.

## 7. Overlay tenant — `objects/12_overlay.yml`

**This is the one place Fabric-D deliberately does *not* mirror Fabric-B/C, and it is required.**

Tenant `Blue` is pinned to `fabric: "Fabric-A"` (`objects/12_overlay.yml:8`), and the day-two tenant `Red`
(`data/tenant-red.yml`) is Fabric-A as well. Fabric-B and Fabric-C therefore have **no tenant, no VRF and no
segments** — their leaves render the EVPN control plane but no `switch-options`, `vlans`, `irb` or
`routing-instances` at all.

Mirroring B/C faithfully would leave Fabric-D in the same state, which makes spec acceptance scenario **AS-1
unsatisfiable** (a Juniper leaf "showing EVPN/VXLAN with tenant segments") and hands the SC-001 reviewer a
config with none of the structure they are there to assess. Fabric-D therefore gets its own tenant.

Scoped to Fabric-D only. Adding tenants to Fabric-B/C would change their rendered configs and violate
**FR-010** (existing vendors unchanged), so it is out of scope here.

Append to the three existing `data:` lists in `objects/12_overlay.yml` — no new documents, no new file:

```yaml
# NetworkTenant
    - name: "Green"
      fabric: "Fabric-D"
      member_of_groups: ["tenants"]

# NetworkVrf
    - name: "green-prod"
      tenant: "Green"

# NetworkSegment
    # Two routed (IRB) segments; placement left empty -> every leaf in Fabric-D.
    - name: "green-web"
      vrf: ["Green", "green-prod"]
      routed: true
    - name: "green-app"
      vrf: ["Green", "green-prod"]
      routed: true
    # L2-only segment (no gateway) — exercises contract A5 on Junos:
    # a `vlans` entry with its VNI but no `l3-interface` and no `irb` unit.
    - name: "green-l2"
      vrf: ["Green", "green-prod"]
      routed: false
```

`vlan_id`, `l2vni`, `route_target`, `subnet` and `gateway` are allocated by the OverlayGenerator — none are
declared here, matching how tenant Blue is defined. The tenant must carry `member_of_groups: ["tenants"]` so
the `generate-tenant` generator picks it up.

The `green-l2` segment is not decoration: it is the only way contract **A5** (gateway-less segment renders a
`vlans` entry but no `l3-interface`) becomes verifiable on Juniper.

## 8. Resulting device inventory

| Fabric | Vendor | Super-spines | Spines | Leaves | Devices |
|---|---|---|---|---|---|
| Fabric-A | Cisco | 6 | 8 | 11 | 25 |
| Fabric-B | Arista | 4 | 8 | 11 | 23 |
| Fabric-C | Dell | 4 | 8 | 11 | 23 |
| **Fabric-D** | **Juniper** | **4** | **8** | **11** | **23** |
| | | | | | **~94 total** |

Interfaces added by Fabric-D: 4×65 (super-spine) + 8×65 (spine) + 11×57 (leaf, plus one runtime VTEP
loopback each) ≈ 1,400.

## 9. Registration

`.infrahub.yml` gains one `jinja2_transform` and one `artifact_definition`. See
[contracts/juniper-registration.md](./contracts/juniper-registration.md).
