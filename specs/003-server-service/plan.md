# Implementation Plan: Connect L2/L3 Servers to Leaves via a Server Service

**Branch**: `dga/feat-server-cilium-r9uuo` (feature dir `003-server-service`) | **Date**: 2026-07-19 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/003-server-service/spec.md`, grounded in the PRD on
[issue #51](https://github.com/opsmill/infrahub-solution-ai-dc/issues/51#issuecomment-5015062739) and a
prior grilling session. Follows ADR-0002 (standalone generator), ADR-0004 (trigger via materialized
placement), ADR-0005 (stored BGP sessions + `rr_client`).

## Summary

Add the first workload-attachment capability to the fabric. An operator declares one **Server service**
design object (`NetworkServerService`: L2/L3, a VRF, optional Rack/leaf-port, and — for L2 — a Segment); a
new standalone **ServerGenerator** materializes a **`NetworkServer`** implementation object plus its
interfaces, picks the least-utilized Rack and lowest free `server`-role leaf port (honoring explicit input,
failing loud on invalid), and cables server↔leaf.

- **L3:** allocate a /31 (rack-side on the leaf, role `server_p2p`), allocate a private server ASN, and
  upsert an eBGP `ipv4_unicast` session on **both** the leaf and the server (paired, correct remote-AS each
  side, `rr_client: false`). The leaf startup-config renders the server interface, /31, and eBGP neighbor.
- **L2:** add the leaf's Rack to the named Segment's `racks` placement; no fabric-side BGP or IP.

The design reuses the established patterns wholesale — the design/implementation split (ADR-0002), the
`GeneratorTarget` checksum trigger, the paired-session upsert (`overlay.upsert_evpn_session`), the p2p
addressing helper (`addressing.assign_ip_addresses_to_p2p_connections`), role-based IPAM, and the per-vendor
startup-config transform. It is additive: new `schemas/server.yml`, new `src/.../servers.py`, a new
generator, small extensions to `routing.yml`/`ipam.yml`/`logical_design.yml`, the three `.j2` templates, and
registration.

## Technical Context

**Language/Version**: Python ≥3.11 (target 3.12).

**Primary Dependencies**: Infrahub SDK (`infrahub-sdk[all]`), `invoke`, `uv`, Jinja2 (config templates),
GraphQL (generator/transform queries). Infrahub Resource Manager (`CoreNumberPool`, `CoreIPPrefixPool`) for
server-ASN and /31 allocation.

**Storage**: Infrahub graph database (system of record). All data flows through the SDK/GraphQL; generated
leaf configs are stored as Infrahub artifacts. The `NetworkServer` is data-only (no artifact).

**Testing**: `pytest` — pure-function unit tests (mirroring `tests/unit/test_overlay.py`,
`test_overlay_placement.py`, `test_vendors.py`) plus an integration test against a Dockerized Infrahub
(mirroring `tests/integration/test_overlay_daytwo.py`).

**Target Platform**: Linux + Docker Compose (`inv start`).

**Project Type**: Infrahub solution repository — schema (YAML) + Generators (Python) + Transforms
(Python/Jinja2) + object data (YAML) + artifact definitions, registered in `.infrahub.yml`. Not a generic
app/library layout.

**Performance Goals**: Not latency-sensitive. The generator MUST be **idempotent** (SC-003) and **scoped**
(only the affected leaf's artifact regenerates). Demo scale: a handful of servers per rack.

**Constraints**: (1) `NetworkServer` MUST NOT inherit `CoreArtifactTarget` — never swept into
`devices`/`{vendor}_devices` groups or startup-config artifacts. (2) **Fail-loud** on invalid placement,
Segment-not-in-VRF, pool exhaustion, and contradictory L3+Segment — following the `vendors.py` convention
(`msg = ...; raise ValueError(msg)`). (3) Single-homed only (one leaf port ↔ one server port). (4) A
`CoreNumberPool` binds to exactly one (node, attribute); pool-allocated values are not readable on the
returned node → **re-fetch** with `client.get()`. (5) Overlay relationships written on leaves must not
re-trigger the physical cascade (ADR-0004 caveat).

**Scale/Scope**: 2 new schema nodes + 1 new generic; edits to 3 existing schema files; 1 new generator
(+`.gql` + query model); a new core-lib module; 3 template extensions + startup query edit; 2 new pools;
1 new group + trigger rule + registration; seed data; unit + integration tests.

### Items to verify during implementation (non-blocking — see research.md)

- `from_pool` allocation on a **new `NetworkServer.asn` Number attribute** across re-runs (guard
  "allocate only if unset"); whether a global `CoreNumberPool` on `NetworkServer.asn` behaves as expected.
- Generalizing `NetworkBGPSession.device`/`peer_device` to a `NetworkBGPPeer` generic — confirm existing
  overlay session upserts and the startup-config query still resolve after the peer type widens.
- Server-port ownership: `NetworkInterface.device` becoming optional + a new `server` owner relationship —
  confirm the existing `[[device, name__value]]` uniqueness constraint and current queries tolerate it.
- Whether adding a Rack to `NetworkSegment.racks` (L2) should auto-re-trigger the OverlayGenerator so the
  leaf actually carries the segment, or whether that stays a separate operator step (see research SD8).

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

`.specify/memory/constitution.md` is the **unpopulated template** (placeholder principles only) — there are
no ratified project-specific gates. The plan instead adheres to the solution's established, documented
engineering principles (`CONTEXT.md`, ADRs, `AGENTS.md`):

- **Design vs implementation split** — operator declares intent (`NetworkServerService`); a generator
  produces implementation (`NetworkServer` + cabling/IP/BGP). ✅ (ADR-0002)
- **One generator owns one concern, triggered by its own design object; idempotent; scoped.** ✅
  (ADR-0002, ADR-0004)
- **Reuse existing patterns** — `GeneratorTarget` checksum, Resource Manager pools, paired session upsert,
  p2p addressing helper, role-based IPAM, the per-device artifact path, fail-loud errors. ✅
- **No disruption to the existing build** — additive schema/objects; server nodes excluded from device
  groups and artifacts. ✅
- **Code style** — Ruff `ALL`, mypy strict, 120-char lines, typed async generators. ✅

**Gate result: PASS** (no violations → Complexity Tracking left empty). Re-checked post-design: still PASS.

## Project Structure

### Documentation (this feature)

```text
specs/003-server-service/
├── plan.md              # This file
├── research.md          # Phase 0 — server decisions SD1–SD11 + validated SDK/GraphQL mechanics
├── data-model.md        # Phase 1 — NetworkServerService/NetworkServer + NetworkBGPPeer generic + edits
├── quickstart.md        # Phase 1 — end-to-end validation guide (L3, L2, explicit placement, idempotency)
├── contracts/           # Phase 1 — GraphQL query, .infrahub.yml/triggers registration, config artifact
│   ├── graphql-queries.md
│   ├── infrahub-registration.md
│   └── config-artifact.md
├── checklists/
│   └── requirements.md  # from /speckit-specify
└── tasks.md             # Phase 2 output (/speckit-tasks — NOT created here)
```

### Source Code (repository root)

The feature extends the existing Infrahub solution layout; touched paths:

```text
schemas/
├── server.yml                # NEW — NetworkServerService (GeneratorTarget) + NetworkServer
├── routing.yml               # EDIT — NEW generic NetworkBGPPeer; repoint NetworkBGPSession.device/peer_device
├── device.yml                # EDIT — NetworkInterface: optional `server` owner rel; `device` made optional
├── ipam.yml                  # EDIT — IpamIPPrefix.role += server_p2p
└── logical_design.yml        # EDIT — NetworkPod.server_prefix_pool (CoreIPPrefixPool)

src/infrahub_solution_ai_dc/
├── servers.py                # NEW (deep) — least-utilized rack + tie-break, port selection, fail-loud
│                             #   validation, /31 + server-ASN allocation, server↔leaf eBGP session upsert
└── protocols.py              # REGENERATE from schema

generators/
├── generate_server.py        # NEW — class ServerGenerator (InfrahubGenerator; GeneratorTarget checksum)
├── generate_server.gql       # NEW
├── generate_server_query.py  # NEW (hand-written pydantic model, per convention)
└── generate_pod.py           # EDIT — allocate_resource_pools(): create + attach the per-Pod server /31 pool

transforms/
├── startup_config.gql        # EDIT — bgp_sessions: add address_family, local_as, peer /31 address; server iface IP
└── templates/startup_config_{cisco,arista,dell}.j2  # EDIT — server-port branch (no switchport + /31);
                                                      #   ipv4_unicast eBGP neighbor branch (peer over /31)

objects/
├── 04_ipam.yml               # EDIT — server /31 supernet (source for the per-Pod server_p2p pool)
├── 07_pools.yml              # EDIT — NEW global "Server ASN Pool" (CoreNumberPool → NetworkServer.asn)
├── 01_groups.yml             # EDIT — NEW server_services CoreStandardGroup
└── 13_servers.yml            # NEW — example L3 (Cilium) Server service seed

triggers.yml                  # EDIT — CoreGeneratorAction run-server-generator + CoreNodeTriggerRule (checksum)
.infrahub.yml                 # EDIT — register generate_server query + generator_definition (targets: server_services)
menus/menu.yml                # EDIT (optional) — Servers menu group

tests/
├── unit/test_servers.py                  # NEW — pure helpers + fail-loud paths
└── integration/test_server_service.py    # NEW — L2/L3/explicit journeys + idempotent re-run
```

**Structure Decision**: Follow the existing Infrahub solution structure. The feature is additive — a new
schema file, a new core-lib module, a new generator, and surgical edits to existing schema/templates/
registration — to satisfy the "no disruption" constraint and keep `NetworkServer` cleanly out of the device
config path.

## Complexity Tracking

> No Constitution Check violations — section intentionally empty.
