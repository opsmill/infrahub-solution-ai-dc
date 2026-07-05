# Quickstart: Validating the EVPN/VXLAN Overlay

End-to-end validation that the overlay works. Assumes the implementation (per `plan.md`, `data-model.md`,
`contracts/`) is in place. Commands use the project's `invoke` tasks (`inv`) and `uv`.

## Prerequisites

- `uv sync --all-packages` has run; Docker available.
- Familiarity with the existing build (`inv start`, `inv load`) — see `AGENTS.md`.

## 1. Static checks

```bash
inv lint        # yamllint + ruff + mypy (strict) — schema YAML and new Python must pass
inv test        # pytest — new unit tests (RT/RD formatting, tier-ordering RR, VTEP alloc,
                #          Device↔Segment materialization, advertise-all default) must pass
```

**Expected**: lint clean; all unit tests green.

## 2. Schema converges

```bash
inv load-schema     # loads schemas/ incl. new overlay.yml + edits
```

**Expected**: schema loads without error; new kinds `NetworkTenant`, `NetworkVrf`, `NetworkSegment` exist,
plus `NetworkDevice.asn`/`vtep_ip`/`segments`, `NetworkFabric.overlay_asn`/`routing_design`, interface roles
`vtep`/`svi`, and the new IPPrefix roles. (Integration test mirrors `tests/integration/test_infrahub.py`.)

## 3. Full build + overlay seed

```bash
inv load            # schema → menu → objects (incl. 07_pools.yml, 12_overlay.yml) → repository
inv start           # bring up the stack; generators run via triggers
```

**Expected after generators settle**:

- Every device has `asn == its fabric.overlay_asn` (allocated once from the global ASN pool).
- Each **leaf** has a `vtep_ip` and a `vtep`-role loopback interface; **spines/super-spines** do not.
- The seed tenant (e.g. "Blue") has a VRF with an allocated `l3vni` + `l3_vlan_id` + `route_target`, and its
  routed segments each have an allocated `vlan_id`, `l2vni`, `route_target`, a `tenant_subnet`, and a `.1`
  `gateway`.
- The segments are materialized onto leafs (advertise-all → every leaf in the fabric, since seed placement
  is empty).

Verify via the Infrahub UI / GraphQL (or the Infrahub MCP tools): query a `NetworkSegment` and confirm its
allocated ids + `route_target`; query a leaf `NetworkDevice` and confirm `segments` + `vtep_ip`.

## 4. Inspect the rendered config artifact (the core proof — User Story 1)

Open the `startup_configuration` artifact for a **leaf** and confirm (per `contracts/config-artifact.md`):

- OSPF underlay intact, now advertising the vtep loopback.
- `router bgp <asn>` with iBGP L2VPN-EVPN neighbors to its cabled spines.
- `interface nve1` (source = loopback1), per-segment `member vni <l2vni>`, per-VRF `member vni <l3vni>
  associate-vrf`.
- `vlan/vn-segment` for each segment + the L3 transit VLAN; `vrf context` with `rd`/`route-target`; the L3
  transit SVI (`ip forward`); and an anycast SVI for each IRB segment.

Open a **spine** artifact and confirm: EVPN sessions with `route-reflector-client` toward its leafs and
client config toward super-spines; **no** NVE/VLAN/VRF/SVI. A **super-spine** shows RR-client toward spines
only. (Validates FR-007, SC-004, SC-006.)

## 5. Day-two scoped change (User Story 2)

Add a second segment to the seed tenant (on a branch, mirroring the `add-rack` workflow), let the
OverlayGenerator run, then:

**Expected**: the new segment appears on the carrying leafs; **only those leafs'** `startup_configuration`
artifacts change — unrelated devices' artifacts are byte-identical (SC-003).

## 6. Placement & L2-only variations (User Story 3)

- Create a segment with `racks` set to a single rack → confirm it renders **only** on that rack's leaves
  (SC-005).
- Create a segment with **no** `gateway` → confirm it renders `vlan`/`vn-segment`/NVE membership but **no**
  anycast SVI (SC-007).

## Success mapping

| Step | Validates |
|------|-----------|
| 1–2  | No-disruption build, schema convergence (SC-006, FR-010) |
| 3    | Auto-allocation, zero manual ids (SC-001, SC-002) |
| 4    | Routed multi-tenant overlay, leaf-only VTEP/state (US1, FR-004/006/007, SC-004) |
| 5    | Scoped day-two regeneration (US2, FR-009, SC-003) |
| 6    | Rack placement + L2-only (US3, FR-005/008, SC-005, SC-007) |
