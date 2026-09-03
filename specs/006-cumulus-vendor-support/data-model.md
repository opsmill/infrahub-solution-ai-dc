# Phase 1 Data Model: NVIDIA Cumulus Linux Vendor Support

Every entity below is an **instance of an existing kind**. No new node kinds, no new attributes, no new
relationships — see [research.md](./research.md) "Cross-cutting: what does not change".

## 1. Vendor group — `objects/01_groups.yml`

One addition, alongside the five existing vendor groups:

```yaml
    - name: cumulus_devices
      parent: devices
```

Membership is **not** declared here. It is stamped at device-creation time by the generators via
`member_of_groups=["devices", self.vendor_group]`, where `vendor_group` is resolved from the device
template's manufacturer. Group name derivation: `f"{manufacturer.name.strip().lower()}_devices"`.

## 2. Manufacturer — `objects/02_manufacturer.yml`

```yaml
    - name: Cumulus
```

Case is display-only; resolution lowercases before matching `SUPPORTED_VENDORS`. See research.md D2 for why
this is modelled as a manufacturer entry.

## 3. Device types — `objects/03_device_type.yml`

Four device types, named after the Spectrum ASIC generation — see research.md D7:

```yaml
    # NVIDIA Spectrum-2, 6.4 Tbps, 64x 100G (modeled radix) -- spine & super-spine. Most established of
    # the three generations.
    - name: "Cumulus-SPECTRUM2"
      manufacturer: ["Cumulus"]
    # NVIDIA Spectrum-3, 12.8 Tbps, 64x 200G (modeled radix) -- spine & super-spine.
    - name: "Cumulus-SPECTRUM3"
      manufacturer: ["Cumulus"]
    # NVIDIA Spectrum-4, 51.2 Tbps, 64x 800G (modeled radix) -- spine & super-spine. Newest, least
    # field-proven generation modeled here.
    - name: "Cumulus-SPECTRUM4"
      manufacturer: ["Cumulus"]
    # NVIDIA Spectrum-2, access-optimized port configuration: 48x 25G SFP28 access + 6x 100G QSFP28
    # uplink -- leaf. Same ASIC generation as Cumulus-SPECTRUM2, different port mix (research.md D7).
    - name: "Cumulus-SPECTRUM2-TOR"
      manufacturer: ["Cumulus"]
```

| Device type | ASIC | Role | Ports |
|---|---|---|---|
| Cumulus-SPECTRUM2 | Spectrum-2 | spine + super-spine | 64× 100G |
| Cumulus-SPECTRUM3 | Spectrum-3 | spine + super-spine | 64× 200G |
| Cumulus-SPECTRUM4 | Spectrum-4 | spine + super-spine | 64× 800G |
| Cumulus-SPECTRUM2-TOR | Spectrum-2 | leaf (compute + storage) | 48× 25G SFP28 + 6× 100G QSFP28 |

`manufacturer` is given as a single-element list because `NetworkDeviceType`'s human-friendly ID is
`[manufacturer__name__value, name__value]` (`schemas/device.yml:40-42`). See research.md D7 for the capacity
figures and the maturity note on `Cumulus-SPECTRUM4`.

## 4. Device templates — `objects/06_device_template.yml`

Eight `TemplateNetworkDevice` entries, appended after the existing twenty-four (four vendors × four/eight
each plus SONiC's eight) — one spine + one super-spine template per Spectrum generation (2/3/4), plus the two
leaf templates (compute/storage) on `Cumulus-SPECTRUM2-TOR`. All reuse the **existing vendor-neutral interface
profiles** from `objects/05_profiles.yml` — no new profiles.

Port-role split follows the established convention exactly: super-spines face spines; spines split
lower-half-to-leaf / upper-half-to-super-spine; leaves split access-ports / spine-facing uplinks; every
template declares exactly one `Loopback0` with `role: "loopback"` and no profile. **The interface shape is
identical across all three Spectrum generations** — only the `device_type` each template points at differs.

| Template name | Role | Device type | Interfaces → profile |
|---|---|---|---|
| `cumulus-spectrum2-super-spine-switch` | `super_spine` | Cumulus-SPECTRUM2 | `Loopback0` (role `loopback`)<br>`swp[1-64]` (64 ports) → `profile-interface-spine` |
| `cumulus-spectrum2-spine-switch` | `spine` | Cumulus-SPECTRUM2 | `Loopback0` (role `loopback`)<br>`swp[1-32]` → `profile-interface-leaf`<br>`swp[33-64]` → `profile-interface-super-spine` |
| `cumulus-spectrum3-super-spine-switch` | `super_spine` | Cumulus-SPECTRUM3 | same shape, device type Cumulus-SPECTRUM3 |
| `cumulus-spectrum3-spine-switch` | `spine` | Cumulus-SPECTRUM3 | same shape, device type Cumulus-SPECTRUM3 |
| `cumulus-spectrum4-super-spine-switch` | `super_spine` | Cumulus-SPECTRUM4 | same shape, device type Cumulus-SPECTRUM4 |
| `cumulus-spectrum4-spine-switch` | `spine` | Cumulus-SPECTRUM4 | same shape, device type Cumulus-SPECTRUM4 |
| `cumulus-spectrum2-tor-leaf-switch-compute` | `leaf` | Cumulus-SPECTRUM2-TOR | `Loopback0` (role `loopback`)<br>`swp[1-48]` (48 ports) → `profile-interface-server`<br>`swp[49-54]` (6 ports) → `profile-interface-spine` |
| `cumulus-spectrum2-tor-leaf-switch-storage` | `leaf` | Cumulus-SPECTRUM2-TOR | `Loopback0` (role `loopback`)<br>`swp[1-48]` (48 ports) → `profile-interface-compute`<br>`swp[49-54]` (6 ports) → `profile-interface-spine` |

Only Fabric-F's three pods (§5) determine which of the three spine/super-spine generations actually gets
built — all three templates exist and are used, none is dead catalog data (research.md D8).

Interface names use Cumulus Linux's real, single naming convention (`swpN`) — see research.md D3.

**Shape**, mirroring the existing entries (`parameters: expand_range: true` on both the device-template spec
and each nested interface block). Shown for Spectrum-2; Spectrum-3 and Spectrum-4 are byte-identical except
for `template_name` and `device_type`:

```yaml
    # Cumulus Linux on NVIDIA Spectrum-2 (Cumulus-SPECTRUM2, 64x 100G) — spine & super-spine.
    - template_name: "cumulus-spectrum2-spine-switch"
      device_type: ["Cumulus", "Cumulus-SPECTRUM2"]
      role: "spine"
      interfaces:
        kind: TemplateNetworkInterface
        parameters:
          expand_range: true
        data:
          - template_name: "CumulusSpectrum2SpineSwitchLoopback0"
            name: "Loopback0"
            role: "loopback"
          - template_name: "CumulusSpectrum2SpineSwitchswp[1-32]"
            name: "swp[1-32]"
            profiles: ["profile-interface-leaf"]
          - template_name: "CumulusSpectrum2SpineSwitchswp[33-64]"
            name: "swp[33-64]"
            profiles: ["profile-interface-super-spine"]
```

The Spectrum-3/4 spine and all three super-spine templates repeat this exact shape with `CumulusSpectrum2` →
`CumulusSpectrum3`/`CumulusSpectrum4` in every `template_name` and `device_type: ["Cumulus",
"Cumulus-SPECTRUM3"]`/`["Cumulus", "Cumulus-SPECTRUM4"]` — no other line changes, mirroring SONiC's own
copy-paste-rename convention for a future fourth generation.

Interface `template_name` follows the existing PascalCase-no-separator convention with the interface name
embedded verbatim, matching the SONiC/Juniper convention. These names only need to be globally unique.

**Range expansion is verified** for the `swp[a-b]` form — plain two-number bracket expression, the same
mechanic already verified for `Eth1/[a-b]` (SONiC) and `Ethernet1/[a-b]` (Dell) — see research.md D3.

### Loopbacks

Each template declares only `Loopback0`. The **second** loopback, `Loopback1` (role `vtep`), is created
imperatively at `src/infrahub_solution_ai_dc/addressing.py` for leaves only. Both keep their vendor-neutral
names in the data model and are rendered in Cumulus Linux form (two `address` lines under one `lo` stanza) by
the Cumulus template — see [research.md](./research.md) D4 and
[contracts/cumulus-config-contract.md](./contracts/cumulus-config-contract.md).

## 5. Fabric — `objects/10_fabric.yml`

Fabric-F mirrors Fabric-E's **topology** exactly (device counts, pod structure). `amount_of_spines` is not
set (defaults to 4), matching every prior fabric. It gets its own overlay tenant (see §7), and — mirroring
Fabric-E's precedent (research.md D8) — **each of its three pods is built from a different Spectrum
generation**:

```yaml
    # Fabric-F — Cumulus Linux (NVIDIA Spectrum ASICs). Mirrors Fabric-E's topology; like Fabric-E, its
    # three pods deliberately use three different Spectrum generations (research.md D8) so all three are
    # visible in one running demo: Pod-F1 (super-spine) on the newest silicon, Pod-F2/F3 (spine) on the two
    # established generations.
    - name: "Fabric-F"
      index: 6
      member_of_groups: ["fabrics"]
      super_spine_switch_template: "cumulus-spectrum4-super-spine-switch"
      amount_of_super_spines: 4
      children:
        kind: NetworkPod
        data:
          - name: "Pod-F1"
            index: 1
            role: "fabric"
            member_of_groups: ["pods"]
          - name: "Pod-F2"
            index: 2
            spine_switch_template: "cumulus-spectrum2-spine-switch"
            member_of_groups: ["pods"]
          - name: "Pod-F3"
            index: 3
            spine_switch_template: "cumulus-spectrum3-spine-switch"
            member_of_groups: ["pods"]
```

`Pod-F1` carries `role: "fabric"` and gets **no** spine template — it is the super-spine pod, and its
super-spines are built from `Fabric-F.super_spine_switch_template`
(`cumulus-spectrum4-super-spine-switch`), not from a pod-level field. Addressing and the overlay ASN are
allocated automatically per fabric (research.md D8), so no manual IPAM entries are needed.

## 6. Racks — `objects/11_rack.yml`

Eight racks, mirroring the Fabric-E block with the Cumulus leaf templates. All live in the existing `Hall-A1`.
Leaves are **not** part of the three-generation split — every rack, in both Pod-F2 and Pod-F3, uses the same
`Cumulus-SPECTRUM2-TOR` leaf regardless of which Spectrum generation that pod's spines use.

| Rack | Index | `rack_type` | Pod | `amount_of_leafs` | Leaf template |
|---|---|---|---|---|---|
| Rack-F2-1 | 1 | compute | Pod-F2 | 2 | `cumulus-spectrum2-tor-leaf-switch-compute` |
| Rack-F2-2 | 2 | compute | Pod-F2 | 1 | `cumulus-spectrum2-tor-leaf-switch-compute` |
| Rack-F2-3 | 3 | compute | Pod-F2 | 2 | `cumulus-spectrum2-tor-leaf-switch-compute` |
| Rack-F2-4 | 4 | storage | Pod-F2 | 1 | `cumulus-spectrum2-tor-leaf-switch-compute` |
| Rack-F3-1 | 1 | compute | Pod-F3 | 2 | `cumulus-spectrum2-tor-leaf-switch-compute` |
| Rack-F3-2 | 2 | compute | Pod-F3 | 1 | `cumulus-spectrum2-tor-leaf-switch-compute` |
| Rack-F3-3 | 3 | storage | Pod-F3 | 1 | `cumulus-spectrum2-tor-leaf-switch-storage` |
| Rack-F3-4 | 4 | compute | Pod-F3 | 1 | `cumulus-spectrum2-tor-leaf-switch-storage` |

> **Mirror faithfully, including the quirks.** As with every prior fabric, two rows have `rack_type` and the
> chosen leaf template disagree — `Rack-F2-4` is `storage` but uses the *compute* template, and `Rack-F3-4` is
> `compute` but uses the *storage* template. Fabric-F reproduces it so all six fabrics stay directly
> comparable; "fixing" it here would make Fabric-F the odd one out and is out of scope.

Total: 11 leaves, matching every existing fabric.

## 7. Overlay tenant — `objects/12_overlay.yml`

**Required**, exactly as Fabric-D's tenant `Green` and Fabric-E's tenant `Purple` were required (research.md
D8): without it, no Cumulus leaf renders any overlay configuration and FR-007 is only vacuously satisfiable.

Append to the three existing `data:` lists in `objects/12_overlay.yml` — no new documents, no new file:

```yaml
# NetworkTenant
    - name: "Amber"
      fabric: "Fabric-F"
      member_of_groups: ["tenants"]

# NetworkVrf
    - name: "amber-prod"
      tenant: "Amber"

# NetworkSegment
    # Two routed (IRB) segments; placement left empty -> every leaf in Fabric-F.
    - name: "amber-web"
      vrf: ["Amber", "amber-prod"]
      routed: true
    - name: "amber-app"
      vrf: ["Amber", "amber-prod"]
      routed: true
    # L2-only segment (no gateway) -- exercises the Cumulus config-contract case:
    # a VNI map entry with no VRF binding.
    - name: "amber-l2"
      vrf: ["Amber", "amber-prod"]
      routed: false
```

`vlan_id`, `l2vni`, `route_target`, `subnet` and `gateway` are allocated by the OverlayGenerator — none are
declared here, matching how tenants Blue/Green/Purple are defined. The tenant must carry
`member_of_groups: ["tenants"]` so the `generate-tenant` generator picks it up.

`amber-l2` is not decoration: it is the only way the L2-only-segment contract case becomes verifiable on
Cumulus.

## 8. Resulting device inventory

| Fabric | Vendor | Super-spines | Spines | Leaves | Devices |
|---|---|---|---|---|---|
| Fabric-A | Cisco | 6 | 8 | 11 | 25 |
| Fabric-B | Arista | 4 | 8 | 11 | 23 |
| Fabric-C | Dell | 4 | 8 | 11 | 23 |
| Fabric-D | Juniper | 4 | 8 | 11 | 23 |
| Fabric-E | SONiC | 4 | 8 | 11 | 23 |
| **Fabric-F** | **Cumulus** | **4** | **8** | **11** | **23** |
| | | | | | **~140 total** |

| Pod | Devices | Device type |
|---|---|---|
| Pod-F1 | 4 super-spines | Cumulus-SPECTRUM4 |
| Pod-F2 | 4 spines + leaves | Cumulus-SPECTRUM2 |
| Pod-F3 | 4 spines + leaves | Cumulus-SPECTRUM3 |

Interfaces added by Fabric-F: 4×65 (super-spine) + 8×65 (spine) + 11×55 (leaf, plus one runtime VTEP loopback
each) ≈ 1,300 — the same order of magnitude every prior vendor addition added.

## 9. Registration

`.infrahub.yml` gains one `jinja2_transform` and one `artifact_definition`. See
[contracts/cumulus-registration.md](./contracts/cumulus-registration.md).
