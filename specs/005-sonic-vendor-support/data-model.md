# Phase 1 Data Model: SONiC Vendor Support

Every entity below is an **instance of an existing kind**. No new node kinds, no new attributes, no new
relationships — see [research.md](./research.md) "Cross-cutting: what does not change".

## 1. Vendor group — `objects/01_groups.yml`

One addition, alongside the four existing vendor groups:

```yaml
    - name: sonic_devices
      parent: devices
```

Membership is **not** declared here. It is stamped at device-creation time by the generators via
`member_of_groups=["devices", self.vendor_group]`, where `vendor_group` is resolved from the device
template's manufacturer. Group name derivation: `f"{manufacturer.name.strip().lower()}_devices"`.

## 2. Manufacturer — `objects/02_manufacturer.yml`

```yaml
    - name: SONiC
```

Case is display-only; resolution lowercases before matching `SUPPORTED_VENDORS`. See research.md D2 for why
this is modelled as a manufacturer entry despite SONiC being an OS, not a hardware maker.

## 3. Device types — `objects/03_device_type.yml`

Four device types, named after the chipset generation rather than any specific ODM box — see research.md D7
for why:

```yaml
    # Broadcom Tomahawk4, 25.6 Tbps, 64x 400G, 4-lane breakout-capable (not modeled -- research.md D11)
    # -- spine & super-spine. Most established of the three generations.
    - name: "SONiC-T4"
      manufacturer: ["SONiC"]
    # Broadcom Tomahawk5, 51.2 Tbps, 64x 800G, 8-lane breakout-capable (not modeled -- research.md D11)
    # -- spine & super-spine.
    - name: "SONiC-T5"
      manufacturer: ["SONiC"]
    # Broadcom Tomahawk6, 102.4 Tbps, 64x 1.6T, 8-lane breakout-capable at a higher per-lane rate (not
    # modeled -- research.md D11) -- spine & super-spine. Newest, least field-proven generation modeled here.
    - name: "SONiC-T6"
      manufacturer: ["SONiC"]
    # Broadcom Trident4-class, 48x 10/25G SFP28 access [fixed-form, not breakout-capable] + 6x 40/100G
    # QSFP28 uplink [4-lane breakout-capable] (not modeled -- research.md D11) -- leaf.
    - name: "SONiC-TD4"
      manufacturer: ["SONiC"]
```

| Device type | Chipset | Role | Ports |
|---|---|---|---|
| SONiC-T4 | Tomahawk4 | spine + super-spine | 64× 400G |
| SONiC-T5 | Tomahawk5 | spine + super-spine | 64× 800G |
| SONiC-T6 | Tomahawk6 | spine + super-spine | 64× 1.6T |
| SONiC-TD4 | Trident4-class | leaf (compute + storage) | 48× 10/25G SFP28 + 6× 40/100G QSFP28 |

`manufacturer` is given as a single-element list because `NetworkDeviceType`'s human-friendly ID is
`[manufacturer__name__value, name__value]` (`schemas/device.yml:40-42`). See research.md D7 for the capacity
figures (Broadcom's own published generational numbers) and the maturity caveat on `SONiC-T6`, and D11 for
the chipset breakout-lane fact recorded in the comments above (not modeled as data — no attribute exists for
it, and adding one would be a schema change, out of scope here).

## 4. Device templates — `objects/06_device_template.yml`

Eight `TemplateNetworkDevice` entries, appended to the existing sixteen — one spine + one super-spine
template per chipset generation (T4/T5/T6), plus the two leaf templates (compute/storage) on `SONiC-TD4`. All
reuse the **existing vendor-neutral interface profiles** from `objects/05_profiles.yml` — no new profiles.

Port-role split follows the established convention exactly: super-spines face spines; spines split
lower-half-to-leaf / upper-half-to-super-spine; leaves split access-ports / spine-facing uplinks; every
template declares exactly one `Loopback0` with `role: "loopback"` and no profile. **The interface shape is
identical across all three chipset generations** — only the `device_type` each template points at differs —
because alias-mode naming (research.md D3) doesn't encode speed or lane count.

| Template name | Role | Device type | Interfaces → profile |
|---|---|---|---|
| `sonic-t4-super-spine-switch` | `super_spine` | SONiC-T4 | `Loopback0` (role `loopback`)<br>`Eth1/[1-64]` (64 ports) → `profile-interface-spine` |
| `sonic-t4-spine-switch` | `spine` | SONiC-T4 | `Loopback0` (role `loopback`)<br>`Eth1/[1-32]` → `profile-interface-leaf`<br>`Eth1/[33-64]` → `profile-interface-super-spine` |
| `sonic-t5-super-spine-switch` | `super_spine` | SONiC-T5 | same shape as T4, device type SONiC-T5 |
| `sonic-t5-spine-switch` | `spine` | SONiC-T5 | same shape as T4, device type SONiC-T5 |
| `sonic-t6-super-spine-switch` | `super_spine` | SONiC-T6 | same shape as T4, device type SONiC-T6 |
| `sonic-t6-spine-switch` | `spine` | SONiC-T6 | same shape as T4, device type SONiC-T6 |
| `sonic-td4-leaf-switch-compute` | `leaf` | SONiC-TD4 | `Loopback0` (role `loopback`)<br>`Eth1/[1-48]` (48 ports) → `profile-interface-server`<br>`Eth1/[49-54]` (6 ports) → `profile-interface-spine` |
| `sonic-td4-leaf-switch-storage` | `leaf` | SONiC-TD4 | `Loopback0` (role `loopback`)<br>`Eth1/[1-48]` (48 ports) → `profile-interface-compute`<br>`Eth1/[49-54]` (6 ports) → `profile-interface-spine` |

Only Fabric-E's three pods (§5) determine which of the three spine/super-spine generations actually gets
built — all three templates exist and are used, none is dead catalog data (research.md D8).

Interface names use SONiC's **alias** naming mode (`Eth1/N`, sequential front-panel numbering), not the
default mode's lane-indexed `EthernetN` — see research.md D3 for why, and D10 for why this needs no
comma-list workaround.

Note `profile-interface-compute` carries `role: "storage"` and MTU 9000 (`objects/05_profiles.yml:10-12`) —
the naming is pre-existing and slightly confusing, but the storage leaf uses it exactly as the Dell, Cisco,
Arista and Juniper storage leaves do.

**Shape**, mirroring the existing entries (`parameters: expand_range: true` on both the device-template spec
and each nested interface block) — and, thanks to alias-mode sequential naming, mirroring Dell's
`Ethernet1/[1-64]` shape almost exactly. Shown for T4; T5 and T6 are byte-identical except for
`template_name` and `device_type`:

```yaml
    # SONiC on Broadcom Tomahawk4 (SONiC-T4, 64x 400G) — spine & super-spine.
    - template_name: "sonic-t4-spine-switch"
      device_type: ["SONiC", "SONiC-T4"]
      role: "spine"
      interfaces:
        kind: TemplateNetworkInterface
        parameters:
          expand_range: true
        data:
          - template_name: "SonicT4SpineSwitchLoopback0"
            name: "Loopback0"
            role: "loopback"
          - template_name: "SonicT4SpineSwitchEth1/[1-32]"
            name: "Eth1/[1-32]"
            profiles: ["profile-interface-leaf"]
          - template_name: "SonicT4SpineSwitchEth1/[33-64]"
            name: "Eth1/[33-64]"
            profiles: ["profile-interface-super-spine"]
```

The T5/T6 spine and all three super-spine templates repeat this exact shape with `SonicT4` → `SonicT5`/
`SonicT6` in every `template_name` and `device_type: ["SONiC", "SONiC-T5"]`/`["SONiC", "SONiC-T6"]` — no
other line changes. This is deliberate: it makes a future fourth generation (`SONiC-T7`, whenever it ships) a
pure copy-paste-rename, not a redesign.

Interface `template_name` follows the existing PascalCase-no-separator convention with the interface name
embedded verbatim, matching the Juniper convention (`objects/06_device_template.yml`'s existing
`JuniperQFX5230SpineSwitchet-0/0/[0-31]` style). These names only need to be globally unique.

**Range expansion is verified** for the `Eth1/[a-b]` form — see [research.md](./research.md) D10.

### Loopbacks

Each template declares only `Loopback0`. The **second** loopback, `Loopback1` (role `vtep`), is created
imperatively at `src/infrahub_solution_ai_dc/addressing.py` for leaves only. Both keep their vendor-neutral
names in the data model and are rendered in SONiC form (`Loopback0` interface plus a VXLAN tunnel source
address) by the SONiC template — see [research.md](./research.md) D4 and
[contracts/sonic-config-contract.md](./contracts/sonic-config-contract.md).

## 5. Fabric — `objects/10_fabric.yml`

Fabric-E mirrors Fabric-D's **topology** exactly (device counts, pod structure). `amount_of_spines` is not
set (defaults to 4), matching every prior fabric. It diverges from Fabric-B/C in two respects, both
deliberate: it gets its own overlay tenant (see §7), and — new in this revision — **each of its three pods is
built from a different chipset generation** (research.md D8), rather than one generation used everywhere:

```yaml
    # Fabric-E — SONiC. Mirrors Fabric-D's topology; unlike every prior fabric, its three pods deliberately
    # use three different chipset generations (research.md D8) so all three are visible in one running demo:
    # Pod-E1 (super-spine) on the newest silicon, Pod-E2/E3 (spine) on the two established generations.
    - name: "Fabric-E"
      index: 5
      member_of_groups: ["fabrics"]
      super_spine_switch_template: "sonic-t6-super-spine-switch"
      amount_of_super_spines: 4
      children:
        kind: NetworkPod
        data:
          - name: "Pod-E1"
            index: 1
            role: "fabric"
            member_of_groups: ["pods"]
          - name: "Pod-E2"
            index: 2
            spine_switch_template: "sonic-t4-spine-switch"
            member_of_groups: ["pods"]
          - name: "Pod-E3"
            index: 3
            spine_switch_template: "sonic-t5-spine-switch"
            member_of_groups: ["pods"]
```

`Pod-E1` carries `role: "fabric"` and gets **no** spine template — it is the super-spine pod, and its
super-spines are built from `Fabric-E.super_spine_switch_template` (`sonic-t6-super-spine-switch`), not from
a pod-level field. Addressing and the overlay ASN are allocated automatically per fabric (research.md D8), so
no manual IPAM entries are needed — this is unaffected by which chipset generation each pod uses.

## 6. Racks — `objects/11_rack.yml`

Eight racks, mirroring the Fabric-D block with the SONiC leaf templates. All live in the existing `Hall-A1`.
Leaves are **not** part of the three-generation split — every rack, in both Pod-E2 and Pod-E3, uses the same
`SONiC-TD4` leaf regardless of which chipset generation that pod's spines use. Mixed leaf generations were
not asked for and would double the leaf-side catalog for no story the spec's user stories need.

| Rack | Index | `rack_type` | Pod | `amount_of_leafs` | Leaf template |
|---|---|---|---|---|---|
| Rack-E2-1 | 1 | compute | Pod-E2 | 2 | `sonic-td4-leaf-switch-compute` |
| Rack-E2-2 | 2 | compute | Pod-E2 | 1 | `sonic-td4-leaf-switch-compute` |
| Rack-E2-3 | 3 | compute | Pod-E2 | 2 | `sonic-td4-leaf-switch-compute` |
| Rack-E2-4 | 4 | storage | Pod-E2 | 1 | `sonic-td4-leaf-switch-compute` |
| Rack-E3-1 | 1 | compute | Pod-E3 | 2 | `sonic-td4-leaf-switch-compute` |
| Rack-E3-2 | 2 | compute | Pod-E3 | 1 | `sonic-td4-leaf-switch-compute` |
| Rack-E3-3 | 3 | storage | Pod-E3 | 1 | `sonic-td4-leaf-switch-storage` |
| Rack-E3-4 | 4 | compute | Pod-E3 | 1 | `sonic-td4-leaf-switch-storage` |

> **Mirror faithfully, including the quirks.** Every prior fabric has two rows where `rack_type` and the
> chosen leaf template disagree — `Rack-x2-4` is `storage` but uses the *compute* template, and `Rack-x3-4` is
> `compute` but uses the *storage* template. Fabric-E reproduces it so all five fabrics stay directly
> comparable; "fixing" it here would make Fabric-E the odd one out and is out of scope.

Total: 11 leaves, matching every existing fabric.

## 7. Overlay tenant — `objects/12_overlay.yml`

**This is the one place Fabric-E deliberately does *not* mirror Fabric-B/C, and it is required**, exactly as
Fabric-D's tenant `Green` was required (research.md D8).

Fabric-B and Fabric-C have no tenant, no VRF and no segments — their leaves render the EVPN control plane but
no tenant overlay at all. Mirroring that for Fabric-E would leave acceptance scenario 1 unsatisfiable (a
SONiC leaf "showing EVPN/VXLAN with tenant segments") and hand the SC-001 reviewer a config with none of the
structure they are there to assess. Fabric-E therefore gets its own tenant, scoped to Fabric-E only — adding
tenants to Fabric-B/C would change their rendered configs and violate **FR-010**.

Append to the three existing `data:` lists in `objects/12_overlay.yml` — no new documents, no new file:

```yaml
# NetworkTenant
    - name: "Purple"
      fabric: "Fabric-E"
      member_of_groups: ["tenants"]

# NetworkVrf
    - name: "purple-prod"
      tenant: "Purple"

# NetworkSegment
    # Two routed (IRB) segments; placement left empty -> every leaf in Fabric-E.
    - name: "purple-web"
      vrf: ["Purple", "purple-prod"]
      routed: true
    - name: "purple-app"
      vrf: ["Purple", "purple-prod"]
      routed: true
    # L2-only segment (no gateway) -- exercises the SONiC config-contract case:
    # a VLAN-to-VNI map entry with no VRF binding.
    - name: "purple-l2"
      vrf: ["Purple", "purple-prod"]
      routed: false
```

`vlan_id`, `l2vni`, `route_target`, `subnet` and `gateway` are allocated by the OverlayGenerator — none are
declared here, matching how tenants Blue and Green are defined. The tenant must carry
`member_of_groups: ["tenants"]` so the `generate-tenant` generator picks it up.

The `purple-l2` segment is not decoration: it is the only way the L2-only-segment contract case becomes
verifiable on SONiC.

## 8. Resulting device inventory

| Fabric | Vendor | Super-spines | Spines | Leaves | Devices |
|---|---|---|---|---|---|
| Fabric-A | Cisco | 6 | 8 | 11 | 25 |
| Fabric-B | Arista | 4 | 8 | 11 | 23 |
| Fabric-C | Dell | 4 | 8 | 11 | 23 |
| Fabric-D | Juniper | 4 | 8 | 11 | 23 |
| **Fabric-E** | **SONiC** | **4** | **8** | **11** | **23** |
| | | | | | **~117 total** |

Fabric-E's device count is identical to Fabric-D's — mixing three chipset generations across its three pods
(§5) changes *which* device type each pod's devices are built from, not how many devices exist:

| Pod | Devices | Device type |
|---|---|---|
| Pod-E1 | 4 super-spines | SONiC-T6 |
| Pod-E2 | 4 spines + leaves | SONiC-T4 |
| Pod-E3 | 4 spines + leaves | SONiC-T5 |

Interfaces added by Fabric-E: 4×65 (super-spine) + 8×65 (spine) + 11×55 (leaf, plus one runtime VTEP loopback
each) ≈ 1,300 — unchanged by the three-generation split, same reasoning.

## 9. Registration

`.infrahub.yml` gains one `jinja2_transform` and one `artifact_definition`. See
[contracts/sonic-registration.md](./contracts/sonic-registration.md).
