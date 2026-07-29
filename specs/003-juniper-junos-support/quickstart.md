# Quickstart: Validate Juniper / Junos Vendor Support

End-to-end validation mapping to the spec's Success Criteria (SC-00x), acceptance scenarios (AS-n) and
functional requirements. Run against a **freshly loaded** stack — Fabric-D is additive, but a clean graph
keeps device and artifact counts unambiguous.

## Prerequisites

```bash
uv sync --all-groups --all-extras
inv lint                      # ruff + mypy + yamllint; must pass before loading
inv test                      # unit tests; test_vendors.py must be green (see Scenario 0)
inv destroy && inv start      # fresh stack
inv load                      # schema → menu → objects (incl. Juniper data) → repository
```

Set an admin token for `infrahubctl` (see `dev/guides/`). Manual object loads need an explicit branch:
`infrahubctl object load <file> --branch main`.

## Scenario 0 — The unit tests reflect the new vendor (FR-001, FR-002)

`tests/unit/test_vendors.py:32-35` currently asserts that **Juniper is rejected** and will fail until
re-pointed.

```bash
uv run pytest tests/unit/test_vendors.py -v
```

**Expected**: `Juniper → juniper_devices` passes in the happy-path parametrize;
`test_unsupported_manufacturer_raises_naming_device` still passes using a *different* unsupported
manufacturer; `test_every_supported_vendor_resolves` covers all four vendors.

## Scenario 1 — Juniper data loaded and the group exists (FR-001)

Confirm in the UI or via GraphQL:

- `OrganizationManufacturer` includes `Juniper`.
- `NetworkDeviceType` includes `QFX5230-64CD` and `QFX5120-48Y-8C`, both with manufacturer `Juniper`.
- `CoreStandardGroup` `juniper_devices` exists with `parent = devices`.
- Four Juniper object templates exist, each with its interfaces expanded — the spine template should have
  **65** interfaces (64 × `et-0/0/N` + `Loopback0`), the leaf templates **57** (48 × `xe-` + 8 × `et-` +
  `Loopback0`).
- Tenant `Green` exists with `fabric = Fabric-D` and membership of the `tenants` group, VRF `green-prod`, and
  segments `green-web`, `green-app` (routed) and `green-l2` (L2-only).

**Expected**: range expansion produced discrete interfaces with Junos names, not literal `[0-63]` strings.

## Scenario 2 — Fabric-D generates with correct vendor membership (AS-3, FR-003, FR-004)

Run the generator pipeline for Fabric-D (via the trigger pipeline, or `infrahubctl generator …` for
`generate-fabric`, `generate-pod`, `generate-rack`).

**Expected**:

- 4 super-spines in Pod-D1, 4 spines each in Pod-D2/D3, 11 leaves across the 8 Fabric-D racks — **23 devices**.
- Every Fabric-D device is a member of `devices` **and** `juniper_devices`, and of no other vendor group.
- No device anywhere is in zero vendor groups or in two.
- Leaves carry `xe-0/0/0`–`xe-0/0/47`, `et-0/0/48`–`et-0/0/55`, `Loopback0`, and a runtime-created
  `Loopback1` with role `vtep`.

## Scenario 3 — Cabling pairs the right ports despite the two name families (AS-4, FR-005)

This is the edge case unique to Juniper: `et-` sorts before `xe-` alphabetically, the reverse of port order.

Inspect `NetworkLink` objects between a Fabric-D rack and its pod.

**Expected**: each leaf's uplinks (`et-0/0/48`+, role `spine`) are cabled to distinct spine downlinks
(`et-0/0/0`–`et-0/0/31`, role `leaf`). **No `xe-` access port is ever cabled to a spine.** No port appears in
two links. Four uplinks per leaf are cabled and four remain uncabled (8 uplinks, 4 spines).

## Scenario 4 — Exactly one artifact per device, everywhere (SC-003, FR-006, FR-010)

```bash
# every device should have exactly one "Startup configuration"
```

**Expected**: all ~94 devices — Fabric-A/B/C **and** D — have exactly one `Startup configuration` artifact.
Zero devices with none (registration chain broken) and zero with two (something still targets `devices`).

## Scenario 5 — Junos leaf config is structurally correct (SC-001, AS-1, FR-007, FR-008)

Fetch the artifact for a Fabric-D **leaf** that carries tenant segments.

**Expected**, per [contracts/junos-config-contract.md](./contracts/junos-config-contract.md) acceptance rules:

- Braces balance to zero and never go negative (A1).
- Contains `switch-options` with `vtep-source-interface lo0.1`, `vlans` entries with `vxlan { vni … }`,
  `routing-instances` for the tenant VRF, and `irb` units for gateway-bearing segments (A2, A4).
- A single `lo0` stanza with `unit 0` (router-id) and `unit 1` (VTEP) — **not** `interface Loopback0` /
  `interface Loopback1` (A4).
- The four uncabled uplinks appear as `disable`d interfaces with no address (A7).
- The **L2-only** segment `green-l2` appears as a `vlans` entry with its VNI but **no** `l3-interface` line
  and **no** `irb` unit (A5). This is the only check that exercises the gateway-less path.

## Scenario 6 — Junos spine config carries no tenant overlay (SC-001, AS-2, FR-007)

Fetch the artifact for a Fabric-D **spine** and a **super-spine**.

**Expected**: `protocols bgp` and `protocols evpn` present; **no** `switch-options`, **no** `vlans`, **no**
`routing-instances`, **no** `irb` (A3). `cluster` present on route-reflecting tiers only (A6).

## Scenario 7 — Existing vendors are untouched (SC-003, FR-010)

Render configs for one Cisco, one Arista and one Dell device before and after the change.

**Expected**: **zero-line diff** on all three. Adding a vendor is purely additive.

## Scenario 8 — Day-two overlay change reaches Juniper leaves

Add a fourth segment to the `Green` tenant's `green-prod` VRF and re-run the overlay generator. (The shipped
day-two file `data/tenant-red.yml` is pinned to Fabric-A and does **not** exercise Juniper — use Green.)

**Expected**: carrying Juniper leaves pick up the new segment's `vlans`/`irb`/`routing-instances`; Juniper
spines' configs are **byte-identical** to before (A8) — the same scoped-regeneration property
`tests/integration/test_overlay_daytwo.py` asserts for the other vendors.

## Scenario 9 — SC-002: the abstraction held

```bash
git diff --stat main -- schemas/ generators/
```

**Expected**: **empty**. Zero files changed under `schemas/` and zero under `generators/`. If either is
non-empty, the multivendor abstraction leaked and that is a finding worth recording — it means vendor #5 will
cost as much as the first three.

## Scenario 10 — SE demo walkthrough (SC-004)

Without editing code, and running nothing beyond `inv load` plus the generator pipeline, walk:
Fabric-D design object → generated switches and cabling → rendered Junos startup configuration.

**Expected**: completes with no manual data fixes and no code edits.

## Review gate (SC-001)

Before merge, a reviewer with production Junos experience reviews **one leaf** and **one spine** config.

**Mandate — in scope**: Junos syntax, stanza placement, EVPN/VXLAN structure.
**Mandate — out of scope**: management addressing (`em0` reuses the loopback IP), interface MTU, and
operational services (AAA/NTP/syslog). These are repo-wide simplifications shared by all four vendors; see
spec Out of Scope. Without this scoping the review fails on deliberate choices.

**Expected**: zero blocking structural findings.

## References

- Registration chain: [contracts/juniper-registration.md](./contracts/juniper-registration.md)
- Required Junos output: [contracts/junos-config-contract.md](./contracts/junos-config-contract.md)
- Data inventory: [data-model.md](./data-model.md)
- Decisions and verified mechanics: [research.md](./research.md)
