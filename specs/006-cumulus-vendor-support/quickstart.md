# Quickstart: Validate Cumulus Linux Vendor Support

End-to-end validation mapping to the spec's Success Criteria (SC-00x), acceptance scenarios and functional
requirements. Run against a **freshly loaded** stack — Fabric-F is additive, but a clean graph keeps device
and artifact counts unambiguous.

## Prerequisites

```bash
uv sync --all-groups --all-extras
inv lint                      # ruff + mypy + yamllint; must pass before loading
inv test                      # unit tests; test_vendors.py must be green (see Scenario 0)
inv destroy && inv start      # fresh stack
inv load                      # schema → menu → objects (incl. Cumulus data) → repository
```

Set an admin token for `infrahubctl` (see `dev/guides/`). Manual object loads need an explicit branch:
`infrahubctl object load <file> --branch main`.

## Scenario 0 — The unit tests reflect the new vendor (FR-001, FR-002)

```bash
uv run pytest tests/unit/test_vendors.py tests/unit/test_cumulus_device_templates.py -v
```

**Expected**: `Cumulus → cumulus_devices` passes in the happy-path parametrize; the negative test still
passes using a manufacturer that remains unsupported; `test_every_supported_vendor_resolves` covers all six
vendors; all eight Cumulus device templates pass their wiring/range-expansion assertions.

## Scenario 1 — Cumulus data loaded and the group exists (FR-001)

Confirm in the UI or via GraphQL:

- `OrganizationManufacturer` includes `Cumulus`.
- `NetworkDeviceType` includes `Cumulus-SPECTRUM2`, `Cumulus-SPECTRUM3`, `Cumulus-SPECTRUM4` and
  `Cumulus-SPECTRUM2-TOR`, all with manufacturer `Cumulus`.
- `CoreStandardGroup` `cumulus_devices` exists with `parent = devices`.
- Eight Cumulus object templates exist (spine + super-spine per Spectrum generation, plus two leaf
  templates), each with its interfaces expanded — every spine/super-spine template should have **65**
  interfaces (64 × `swpN` + `Loopback0`) **regardless of generation** — and the leaf templates **55**
  (48 × access `swpN` + 6 × uplink `swpN` + `Loopback0`).
- Tenant `Amber` exists with `fabric = Fabric-F` and membership of the `tenants` group, VRF `amber-prod`, and
  segments `amber-web`, `amber-app` (routed) and `amber-l2` (L2-only).

**Expected**: range expansion produced discrete `swp1`, `swp2`, `swp3`, … interfaces — not literal `[1-64]`
strings.

## Scenario 2 — Fabric-F generates with correct vendor membership (FR-003, FR-004)

Run the generator pipeline for Fabric-F (via the trigger pipeline, or `infrahubctl generator …` for
`generate-fabric`, `generate-pod`, `generate-rack`).

**Expected**:

- 4 super-spines in Pod-F1, 4 spines each in Pod-F2/F3, 11 leaves across the 8 Fabric-F racks — **23
  devices**.
- Every Fabric-F device is a member of `devices` **and** `cumulus_devices`, and of no other vendor group —
  including the super-spines and spines, even though they span three different device types
  (`Cumulus-SPECTRUM2`, `Cumulus-SPECTRUM3`, `Cumulus-SPECTRUM4`). Vendor-group membership is derived from
  manufacturer (`vendors.py`), not from device type, so all three generations resolve to the same
  `cumulus_devices` group.
- No device anywhere is in zero vendor groups or in two.
- Pod-F1's 4 super-spines are built from `cumulus-spectrum4-super-spine-switch` (device type
  `Cumulus-SPECTRUM4`); Pod-F2's 4 spines from `cumulus-spectrum2-spine-switch` (`Cumulus-SPECTRUM2`);
  Pod-F3's 4 spines from `cumulus-spectrum3-spine-switch` (`Cumulus-SPECTRUM3`) — confirm via each device's
  `device_type` relationship, not just its hostname/role.
- Leaves carry `swp1`–`swp48` (access), `swp49`–`swp54` (uplink), `Loopback0`, and a runtime-created
  `Loopback1` with role `vtep` — identical shape regardless of which pod (and therefore which spine
  generation) they connect to.

## Scenario 3 — Cabling pairs the right ports in numeric order (FR-005)

`swpN` is a single sequential family with no separator (like Arista's `EthernetN`), so this is a low-risk
check — confirm `swp10` doesn't sort before `swp2` (naive string order) when pairing uplinks to spine
downlinks.

Inspect `NetworkLink` objects between a Fabric-F rack and its pod.

**Expected**: each leaf's uplinks (`swp49`–`swp54`, role `spine`) are cabled to distinct spine downlinks
(`swp1`–`swp32`, role `leaf`), in numerically correct order — not lexicographic order. No access port is ever
cabled to a spine. No port appears in two links. Four uplinks per leaf are cabled and two remain uncabled (6
uplinks, 4 spines).

## Scenario 4 — Exactly one artifact per device, everywhere (SC-003, FR-006, FR-010)

**Expected**: all ~140 devices — Fabric-A/B/C/D/E **and** F — have exactly one `Startup configuration`
artifact. Zero devices with none (registration chain broken) and zero with two (something still targets
`devices`).

## Scenario 5 — Cumulus leaf config is structurally correct (SC-001, FR-007, FR-008)

Fetch the artifact for a Fabric-F **leaf** that carries tenant segments.

**Expected**, per
[contracts/cumulus-config-contract.md](./contracts/cumulus-config-contract.md) acceptance rules:

- Every `/etc/network/interfaces` stanza is complete — `iface <name>` followed only by its own indented
  attribute lines (A1).
- Contains `auto bridge`/`iface bridge`, a `vni<l2vni>` stanza per segment, and for gateway-bearing segments a
  `vlan<vlan_id>` stanza with `address`/`vrf`, plus an FRR `vrf <name> / vni <l3vni> / exit-vrf` block for the
  tenant VRF (A2).
- `vxlan-local-tunnelip` uses the `vtep`-role interface's address; FRR `bgp router-id` uses the
  `loopback`-role address — never conflated (A4). Neither is ever rendered as a literal `iface Loopback1`.
- The two uncabled uplinks appear with an `iface` stanza carrying `alias`/`link-down yes` and no `auto` line,
  and no `address` line (A7).
- The **L2-only** segment `amber-l2` gets a `vni<l2vni>` stanza and appears in `bridge-vids`, but **no**
  `vlan<vlan_id>` stanza (A5). This is the only check that exercises the gateway-less path.

## Scenario 6 — Cumulus spine config carries no tenant overlay, on every Spectrum generation (SC-001, FR-007)

Fetch the artifact for a spine from **Pod-F2** (`Cumulus-SPECTRUM2`), a spine from **Pod-F3**
(`Cumulus-SPECTRUM3`), and a super-spine from **Pod-F1** (`Cumulus-SPECTRUM4`).

**Expected**: the FRR `router bgp` / `address-family l2vpn evpn` block is present; **no** `bridge` stanza,
**no** `vni<N>` stanza, **no** `vrf ... vni ...` block anywhere in the artifact (A3). `route-reflector-client`
present on route-reflecting tiers only (A6). All three Spectrum generations render **identical** config
structure — `startup_config_cumulus.j2` has no chipset-specific logic (research.md D8), so any difference
beyond hostname and addressing between the Spectrum-2, -3 and -4 artifacts is a bug.

## Scenario 7 — Existing vendors are untouched (SC-003, FR-010)

Render configs for one Cisco, one Arista, one Dell, one Juniper and one SONiC device before and after the
change.

**Expected**: **zero-line diff** on all five. Adding a sixth vendor is purely additive.

## Scenario 8 — Day-two overlay change reaches Cumulus leaves

Add a fourth segment to the `Amber` tenant's `amber-prod` VRF and re-run the overlay generator. (The shipped
day-two file `data/tenant-red.yml` is pinned to Fabric-A and does **not** exercise Cumulus — use Amber.)

**Expected**: Fabric-F leaves pick up the new segment's `vni<l2vni>`/`bridge-vids` lines; Fabric-F spines'
configs are **byte-identical** to before (A8) — the same scoped-regeneration property
`tests/integration/test_overlay_daytwo.py` asserts for the other vendors.

## Scenario 9 — SC-002: the abstraction held

```bash
git diff --stat main -- schemas/ generators/
```

**Expected**: **empty**. Zero files changed under `schemas/` and zero under `generators/`. If either is
non-empty, the multivendor abstraction leaked and that is a finding worth recording — it means vendor #7 will
cost as much as the first one did before `002-multivendor-config` existed.

## Scenario 10 — SE demo walkthrough (SC-004)

Without editing code, and running nothing beyond `inv load` plus the generator pipeline, walk: Fabric-F design
object → generated switches and cabling → rendered Cumulus Linux startup configuration.

**Expected**: completes with no manual data fixes and no code edits.

## Review gate (SC-001)

Before merge, a reviewer with production Cumulus Linux/FRR experience reviews **one leaf** and **one spine**
config.

**Mandate — in scope**: the `/etc/network/interfaces`/FRR split, correct stanza attribution in each section,
EVPN/VXLAN structure. **Mandate — out of scope**: management (`eth0`) addressing, interface MTU, and
operational services (AAA/NTP/syslog). These are repo-wide simplifications shared by all six vendors; see
spec Out of Scope.

**Expected**: zero blocking structural findings.

## References

- Registration chain: [contracts/cumulus-registration.md](./contracts/cumulus-registration.md)
- Required Cumulus output: [contracts/cumulus-config-contract.md](./contracts/cumulus-config-contract.md)
- Data inventory: [data-model.md](./data-model.md)
- Decisions and verified mechanics: [research.md](./research.md)
