# Quickstart: Validate SONiC Vendor Support

End-to-end validation mapping to the spec's Success Criteria (SC-00x), acceptance scenarios and functional
requirements. Run against a **freshly loaded** stack — Fabric-E is additive, but a clean graph keeps device
and artifact counts unambiguous.

## Prerequisites

```bash
uv sync --all-groups --all-extras
inv lint                      # ruff + mypy + yamllint; must pass before loading
inv test                      # unit tests; test_vendors.py must be green (see Scenario 0)
inv destroy && inv start      # fresh stack
inv load                      # schema → menu → objects (incl. SONiC data) → repository
```

Set an admin token for `infrahubctl` (see `dev/guides/`). Manual object loads need an explicit branch:
`infrahubctl object load <file> --branch main`.

## Scenario 0 — The unit tests reflect the new vendor (FR-001, FR-002)

```bash
uv run pytest tests/unit/test_vendors.py -v
```

**Expected**: `SONiC → sonic_devices` passes in the happy-path parametrize; the negative test still passes
using a manufacturer that remains unsupported; `test_every_supported_vendor_resolves` covers all five
vendors.

## Scenario 1 — SONiC data loaded and the group exists (FR-001)

Confirm in the UI or via GraphQL:

- `OrganizationManufacturer` includes `SONiC`.
- `NetworkDeviceType` includes `SONiC-T4`, `SONiC-T5`, `SONiC-T6` and `SONiC-TD4`, all with manufacturer
  `SONiC`.
- `CoreStandardGroup` `sonic_devices` exists with `parent = devices`.
- Eight SONiC object templates exist (spine + super-spine per chipset generation, plus two leaf templates),
  each with its interfaces expanded — every spine/super-spine template should have **65** interfaces
  (64 × `Eth1/N` + `Loopback0`) **regardless of generation** — T4/T5/T6 differ only in which device type they
  reference, not in interface shape — and the leaf templates **55** (48 × access `Eth1/N` + 6 × uplink
  `Eth1/N` + `Loopback0`).
- Tenant `Purple` exists with `fabric = Fabric-E` and membership of the `tenants` group, VRF `purple-prod`, and
  segments `purple-web`, `purple-app` (routed) and `purple-l2` (L2-only).

**Expected**: range expansion produced discrete `Eth1/1`, `Eth1/2`, `Eth1/3`, … interfaces (SONiC's alias
naming mode) — not literal `[1-64]` strings, and not the default mode's lane-indexed `Ethernet0`,
`Ethernet4`, `Ethernet8`, … series (see research.md D3).

## Scenario 2 — Fabric-E generates with correct vendor membership (FR-003, FR-004)

Run the generator pipeline for Fabric-E (via the trigger pipeline, or `infrahubctl generator …` for
`generate-fabric`, `generate-pod`, `generate-rack`).

**Expected**:

- 4 super-spines in Pod-E1, 4 spines each in Pod-E2/E3, 11 leaves across the 8 Fabric-E racks — **23 devices**.
- Every Fabric-E device is a member of `devices` **and** `sonic_devices`, and of no other vendor group —
  including the super-spines and spines, even though they span three different device types (`SONiC-T4`,
  `SONiC-T5`, `SONiC-T6`). Vendor-group membership is derived from manufacturer (`vendors.py`), not from
  device type, so all three generations resolve to the same `sonic_devices` group.
- No device anywhere is in zero vendor groups or in two.
- Pod-E1's 4 super-spines are built from `sonic-t6-super-spine-switch` (device type `SONiC-T6`); Pod-E2's 4
  spines from `sonic-t4-spine-switch` (`SONiC-T4`); Pod-E3's 4 spines from `sonic-t5-spine-switch`
  (`SONiC-T5`) — confirm via each device's `device_type` relationship, not just its hostname/role.
- Leaves carry `Eth1/1`–`Eth1/48` (access), `Eth1/49`–`Eth1/54` (uplink), `Loopback0`, and a runtime-created
  `Loopback1` with role `vtep` — identical shape regardless of which pod (and therefore which spine
  generation) they connect to.

## Scenario 3 — Cabling pairs the right ports in numeric order (FR-005)

SONiC's alias naming is a single sequential family, so this is a much smaller risk than Juniper's two-family
case — the only thing to confirm is that `Eth1/10` doesn't sort before `Eth1/2` (naive string order) when
pairing uplinks to spine downlinks.

Inspect `NetworkLink` objects between a Fabric-E rack and its pod.

**Expected**: each leaf's uplinks (`Eth1/49`–`Eth1/54`, role `spine`) are cabled to distinct spine downlinks
(`Eth1/1`–`Eth1/32`, role `leaf`), in numerically correct order — not lexicographic order. No access port is
ever cabled to a spine. No port appears in two links. Four uplinks per leaf are cabled and two remain
uncabled (6 uplinks, 4 spines).

## Scenario 4 — Exactly one artifact per device, everywhere (SC-003, FR-006, FR-010)

**Expected**: all ~117 devices — Fabric-A/B/C/D **and** E — have exactly one `Startup configuration` artifact.
Zero devices with none (registration chain broken) and zero with two (something still targets `devices`).

## Scenario 5 — SONiC leaf config is structurally correct (SC-001, FR-007, FR-008)

Fetch the artifact for a Fabric-E **leaf** that carries tenant segments.

**Expected**, per [contracts/sonic-config-contract.md](./contracts/sonic-config-contract.md) acceptance rules:

- Every `config` CLI line is a complete, independently valid command (A1).
- Contains `config vlan add`, `config vxlan add`/`evpn_nvo add`/`map add`, `config interface ip add
  Vlan<id>` and `config interface vrf bind` for gateway-bearing segments, and an FRR `vrf <name> / vni
  <l3vni> / exit-vrf` block for the tenant VRF (A2).
- `config vxlan add vtep1 <ip>` uses the `vtep`-role interface's address; FRR `bgp router-id` uses the
  `loopback`-role address — never conflated (A4). Neither is ever rendered as a literal `interface
  Loopback1`.
- The two uncabled uplinks appear with `config interface description`/`shutdown` and no `config interface ip
  add` line (A7).
- The **L2-only** segment `purple-l2` gets `config vlan add` and `config vxlan map add`, but **no**
  `config interface ip add Vlan<id>` and **no** `config interface vrf bind` line (A5). This is the only check
  that exercises the gateway-less path.

## Scenario 6 — SONiC spine config carries no tenant overlay, on every chipset generation (SC-001, FR-007)

Fetch the artifact for a spine from **Pod-E2** (`SONiC-T4`), a spine from **Pod-E3** (`SONiC-T5`), and a
super-spine from **Pod-E1** (`SONiC-T6`).

**Expected**: the FRR `router bgp` / `address-family l2vpn evpn` block is present; **no** `config vlan`, **no**
`config vxlan`, **no** `vrf ... vni ...` block anywhere in the artifact (A3). `route-reflector-client` present
on route-reflecting tiers only (A6). All three chipset generations render **identical** config structure —
`startup_config_sonic.j2` has no chipset-specific logic (research.md D8), so any difference beyond hostname
and addressing between the T4, T5 and T6 artifacts is a bug.

## Scenario 7 — Existing vendors are untouched (SC-003, FR-010)

Render configs for one Cisco, one Arista, one Dell and one Juniper device before and after the change.

**Expected**: **zero-line diff** on all four. Adding a fifth vendor is purely additive.

## Scenario 8 — Day-two overlay change reaches SONiC leaves

Add a fourth segment to the `Purple` tenant's `purple-prod` VRF and re-run the overlay generator. (The
shipped day-two file `data/tenant-red.yml` is pinned to Fabric-A and does **not** exercise SONiC — use
Purple.)

**Expected**: carrying SONiC leaves pick up the new segment's `config vlan`/`config vxlan map` lines; SONiC
spines' configs are **byte-identical** to before (A8) — the same scoped-regeneration property
`tests/integration/test_overlay_daytwo.py` asserts for the other vendors.

## Scenario 9 — SC-002: the abstraction held

```bash
git diff --stat main -- schemas/ generators/
```

**Expected**: **empty**. Zero files changed under `schemas/` and zero under `generators/`. If either is
non-empty, the multivendor abstraction leaked and that is a finding worth recording — it means vendor #6 will
cost as much as the first one did before `002-multivendor-config` existed.

## Scenario 10 — SE demo walkthrough (SC-004)

Without editing code, and running nothing beyond `inv load` plus the generator pipeline, walk: Fabric-E design
object → generated switches and cabling → rendered SONiC startup configuration.

**Expected**: completes with no manual data fixes and no code edits.

## Review gate (SC-001)

Before merge, a reviewer with production SONiC/FRR experience reviews **one leaf** and **one spine** config.

**Mandate — in scope**: the `config`-CLI/FRR split, correct verb usage in each section, EVPN/VXLAN structure.
**Mandate — out of scope**: management (`eth0`) addressing, interface MTU, and operational services
(AAA/NTP/syslog). These are repo-wide simplifications shared by all five vendors; see spec Out of Scope.
Without this scoping the review fails on deliberate choices.

**Expected**: zero blocking structural findings.

## References

- Registration chain: [contracts/sonic-registration.md](./contracts/sonic-registration.md)
- Required SONiC output: [contracts/sonic-config-contract.md](./contracts/sonic-config-contract.md)
- Data inventory: [data-model.md](./data-model.md)
- Decisions and verified mechanics: [research.md](./research.md)
