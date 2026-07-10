# Implementation Plan: EVPN/VXLAN Overlay for the AI/DC Fabric

**Branch**: `wvd-add-overlay` (feature dir `001-evpn-overlay`) | **Date**: 2026-06-29 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/001-evpn-overlay/spec.md`

**Note**: This plan is grounded in a prior grilling session (decisions D1–D14), captured in `CONTEXT.md`
(domain language) and `docs/adr/0001`–`0004` (rationale), and the engineering gap-analysis at
`/home/wim/.claude/plans/evpn-overlay-capability-gap-analysis.md`.

## Summary

Add a multi-tenant EVPN/VXLAN overlay on top of the existing OSPF-underlay Clos fabric. Operators declare
`Tenant → VRF → Segment` design intent; a new **OverlayGenerator** allocates overlay identifiers (VNI/VLAN/
ASN/RT) from Infrahub Resource Manager pools, allocates anycast-gateway subnets, and materializes which
leafs carry which segments. The per-device startup-config transform is expanded to render an **iBGP
L2VPN-EVPN** control plane with **hierarchical route reflection** (leaf→spine→super-spine), **leaf-only
VTEPs**, and **symmetric IRB** (L2VNI bridging + L3VNI routing + distributed anycast gateway). The design
keeps the existing underlay untouched and reserves a `routing_design` switch so an eBGP control plane can be
added later without changing the operator-facing tenant model.

## Technical Context

**Language/Version**: Python ≥3.11 (target 3.12).

**Primary Dependencies**: Infrahub SDK (`infrahub-sdk[all]` — pyproject pins `1.16.0`; local venv has
`1.22.0`), `invoke` task runner, `uv` package manager, Jinja2 (config templates), GraphQL (generator/
transform queries). Infrahub Resource Manager (`CoreNumberPool`, `CoreIPAddressPool`, `CoreIPPrefixPool`,
`CoreIPNamespace`) for allocation.

**Storage**: Infrahub graph database (the system of record). No direct DB access from this code — all data
flows through the Infrahub SDK / GraphQL. Generated configs are stored as Infrahub artifacts.

**Testing**: `pytest` — unit tests with mock objects (see `tests/unit/test_cabling.py`), integration tests
against a Dockerized Infrahub (`infrahub_sdk.testing.docker`, see `tests/integration/test_infrahub.py`).

**Target Platform**: Linux + Docker Compose (the Infrahub stack via `inv start`).

**Project Type**: Infrahub solution repository — schema (YAML) + Generators (Python) + Transforms (Python/
Jinja2) + object data (YAML) + artifact definitions, registered in `.infrahub.yml`. Not a generic
app/library layout.

**Performance Goals**: Not latency-sensitive. Generators must be **idempotent** and **scoped** (a change
regenerates only affected objects/devices). Demo scale: 2 fabrics × 6 pods × 16 racks, hundreds of devices/
links; overlay adds a handful of tenants/VRFs/segments per fabric.

**Constraints**: (1) Must **coexist with the existing OSPF underlay and Fabric→Pod→Rack build** with zero
disruption. (2) Per-fabric overlay scope, no cross-fabric DCI. (3) NX-OS-style config syntax (consistent
with the existing template). (4) One `CoreNumberPool` binds to exactly one (node, attribute) → multiple
pools. (5) Allocated pool values are not readable on the returned node → re-fetch with `client.get()`.

**Scale/Scope**: Adds ~3 new schema nodes (Tenant/VRF/Segment), edits to 3 existing schema files, 1 new
generator + extensions to 3 existing generators, a major transform/template expansion, new resource pools
and seed data, a menu group, registration, and tests.

### Items to verify during implementation (non-blocking — see research.md)

- `from_pool` idempotency on a Number attribute, and whether `infrahubctl object load` supports `from_pool`
  for a Number attribute (affects how `overlay_asn` is allocated).
- The deployed task-worker SDK version (1.16 vs 1.22) — `CoreNumberPool` UX evolved across versions.
- GraphQL `endpoints` inline-fragment traversal: **resolved** — `transforms/computed_interface_description.gql`
  already uses `... on NetworkInterface { device { node {...} } }`.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

`.specify/memory/constitution.md` is the **unpopulated template** (placeholder principles only) — there are
no ratified project-specific gates to evaluate. The plan instead adheres to the solution's established,
documented engineering principles (from `CONTEXT.md`, the ADRs, and `AGENTS.md`):

- **Design vs Implementation split** — operators declare intent (Tenant/VRF/Segment); a Generator produces
  implementation objects. ✅ (ADR-0002)
- **One Generator owns one concern, triggered by its own design object; idempotent; scoped.** ✅ (ADR-0002,
  ADR-0004)
- **Reuse existing patterns** — Resource Manager pools, `GeneratorMixin` checksums, role-based IPAM, the
  per-device artifact path. ✅
- **No disruption to the existing build.** ✅ (FR-010, SC-006)
- **Code style** — Ruff `ALL`, mypy strict, 120-char lines, typed async generators (AGENTS.md). ✅

**Gate result: PASS** (no violations → Complexity Tracking left empty).

## Project Structure

### Documentation (this feature)

```text
specs/001-evpn-overlay/
├── plan.md              # This file
├── research.md          # Phase 0 output — decisions D1–D14 + validated SDK/GraphQL mechanics
├── data-model.md        # Phase 1 output — Tenant/VRF/Segment + edits to Device/Fabric/Pod/Interface/IPPrefix
├── quickstart.md        # Phase 1 output — end-to-end validation guide
├── contracts/           # Phase 1 output — GraphQL query contracts, .infrahub.yml registration, config artifact
│   ├── graphql-queries.md
│   ├── infrahub-registration.md
│   └── config-artifact.md
└── tasks.md             # Phase 2 output (/speckit-tasks — NOT created here)
```

### Source Code (repository root)

The overlay extends the existing Infrahub solution layout; touched paths:

```text
schemas/
├── overlay.yml              # NEW — NetworkTenant, NetworkVrf, NetworkSegment
├── logical_design.yml       # EDIT — NetworkFabric: overlay_asn, routing_design, anycast_gateway_mac; NetworkPod: vtep_pool
├── device.yml               # EDIT — NetworkDevice: asn, vtep_ip, segments; NetworkInterface: roles vtep/svi
└── ipam.yml                 # EDIT — IpamIPPrefix roles: pod_vtep_loopback, overlay_supernet, tenant_subnet

generators/
├── generate_fabric.py       # EDIT — allocate overlay_asn (global ASN pool), stamp device.asn on super-spines
├── generate_pod.py          # EDIT — create per-pod VTEP pool, stamp device.asn on spines
├── generate_rack.py         # EDIT — leaf vtep_ip + vtep loopback interface, stamp device.asn
├── generate_tenant.py       # NEW — OverlayGenerator (alloc VNIs/VLANs/RTs, subnet/gateway, materialize Device↔Segment)
├── generate_tenant.gql      # NEW
└── generate_tenant_query.py # NEW (generated)

transforms/
├── startup_config.gql       # EDIT — add asn, vtep_ip, neighbor loopbacks, device.segments + vrf data
└── templates/startup_config.j2  # EDIT — BGP EVPN (hierarchical RR), NVE, VLAN↔VNI, VRF+transit SVI, anycast SVI

src/infrahub_solution_ai_dc/
├── protocols.py             # REGENERATE from schema
└── addressing.py            # EDIT — optional VTEP-loopback assignment helper

objects/
├── 04_ipam.yml              # EDIT — overlay supernet + tenant_subnet prefix pool
├── 07_pools.yml             # NEW — CoreNumberPool: ASN, L2VNI, L3VNI, VLAN-L2, VLAN-L3
├── 10_fabric.yml            # EDIT — routing_design on fabrics
├── 12_overlay.yml           # NEW — example tenant/VRF/segments
└── 20_triggers.yml(.save)   # EDIT — trigger rule + action for OverlayGenerator

menus/menu.yml               # EDIT — Network → Overlay group
.infrahub.yml                # EDIT — register generate_tenant query + generator_definition
tests/                       # NEW unit + integration tests
```

**Structure Decision**: Follow the existing Infrahub solution structure (schemas/generators/transforms/
objects/menus + `src/infrahub_solution_ai_dc/` library + `.infrahub.yml`). The overlay is additive — new
files where possible, surgical edits to existing generators/transform — to satisfy the "no disruption to the
existing build" constraint.

## Complexity Tracking

> No Constitution Check violations — section intentionally empty.
