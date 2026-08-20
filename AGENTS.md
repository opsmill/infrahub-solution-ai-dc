# AGENTS.md

This file provides guidance to AI coding assistants working with code in this repository.

## Project Overview

Infrahub AI/DC Solution — a reference implementation for automated data center network management. Provides generators, transforms, and artifact definitions for creating network fabrics, pods, and racks using the Infrahub platform.

## Commands

All commands use `invoke` (aliased as `inv`). Dependencies managed with `uv`.

```bash
uv sync --all-packages          # Install dependencies

inv start                       # Start Infrahub stack (docker compose)
inv stop                        # Stop containers
inv destroy                     # Stop and remove everything including volumes
inv restart [--component=NAME]  # Restart all or specific service
inv build [--no-cache]          # Build Docker image

inv load                        # Full load: schema → menu → objects → repository
inv load-schema                 # Load schemas only
inv load-menu                   # Load menus only

inv lint                        # Run all linters (yamllint, ruff, mypy)
inv format                      # Format with ruff
inv test                        # Run pytest
```

Run a single test: `pytest tests/unit/test_computed_attribute.py`

## Architecture

### Core Library (`src/infrahub_solution_ai_dc/`)

- `generator.py` — `GeneratorMixin` providing checksum calculation for change detection
- `protocols.py` — Auto-generated typed node definitions from Infrahub schemas
- `cabling.py` — Cabling plan algorithms
- `addressing.py` — IP addressing utilities
- `sorting.py` — Device/interface sorting utilities
- `overlay.py` — Overlay helpers: route-target/route-reflector logic, iBGP EVPN session upserts, segment-to-leaf placement
- `servers.py` — Server helpers: least-utilized rack + free-port selection, fail-loud service/placement validation, eBGP (`ipv4_unicast`) session upserts
- `vendors.py` — Vendor resolution: maps a device's manufacturer to its `{vendor}_devices` group (fail-loud)
- `clusters.py` — Cluster peering: turns a cluster's members into ordered Cilium peering records; eligibility and deterministic ordering; pure, no client

### Generators (`generators/`)

Five generators that create infrastructure objects via `InfrahubGenerator` + `GeneratorMixin`:

- `generate_fabric.py` — Creates super-spine devices for a fabric; allocates the overlay ASN
- `generate_pod.py` — Creates spine devices for a pod; materializes iBGP EVPN sessions
- `generate_rack.py` — Creates leaf devices for a rack; allocates VTEP loopbacks
- `generate_tenant.py` — `OverlayGenerator` (registered as `generate-tenant`, targets the `tenants` group): allocates overlay identifiers (VNI/VLAN/ASN/route target) and materializes tenant/VRF/segment placement
- `generate_server.py` — `ServerGenerator` (registered as `generate-server`, targets the `server_services` group): connects an L2/L3 `NetworkServerService` to a leaf — picks rack/port, cables it, and for L3 allocates a /31 + server ASN and upserts paired eBGP sessions

Each generator has a paired `.gql` query file and a `*_query.py` generated query model file. Configured in `.infrahub.yml`.

### Transforms (`transforms/`)

- `cabling_plan.py` — CSV cabling plan generation (`InfrahubTransform`)
- `computed_interface_description.py` — Interface description transform
- `cilium_manifest.py` — `CiliumManifest` (`InfrahubTransform`): renders a Kubernetes cluster's Cilium BGP manifest as multi-document YAML — one `CiliumBGPClusterConfig` per eligible L3 member plus one shared `CiliumBGPPeerConfig` and `CiliumBGPAdvertisement`. Selection and ordering live in `clusters.py`; this only maps to Cilium field names. `.infrahub.yml` wires it to an `application/yaml` artifact (`Cilium BGP Manifest`) targeting the `kubernetes_clusters` group.
- `templates/startup_config_{cisco,arista,dell,juniper}.j2` — Per-vendor Jinja2 templates for device startup configs. `.infrahub.yml` wires one Jinja2 transform and one artifact definition per vendor, each targeting the matching `{vendor}_devices` group.

### Data Files

- `schemas/` — Infrahub schema definitions (YAML), including `overlay.yml` (Tenant/VRF/Segment), `routing.yml` (BGP sessions) and `kubernetes.yml` (Kubernetes cluster)
- `objects/` — Object data files loaded in numbered order (01-12) by `inv load`
- `queries/` — Standalone GraphQL queries that belong to no generator or transform: `artifact_ids.gql` (registered as `ArtifactIDs`), which external consumers poll at `/api/query/ArtifactIDs` for artifact id, storage id and checksum
- `triggers.yml` — Top-level trigger rules (`CoreGeneratorAction` + `CoreNodeTriggerRule`); **not** loaded by `inv load`, loaded manually after repository sync
- `data/` — Supplementary data **not** loaded by `inv load`: `permissions.yml` (operator account/roles) and `tenant-red.yml` (a second, day-two overlay tenant); load manually with `infrahubctl object load`
- `menus/` — UI menu definitions
- `.infrahub.yml` — Registers all generators, transforms, queries, and artifact definitions

### Editions

`INFRAHUB_EDITION` (`community`, the default, or `enterprise`) is the single knob selecting which
Infrahub edition the stack runs. `tasks.py` derives the compose file URL, the base image the
`Dockerfile` extends, the runtime user that image expects, and the name of the image this project
builds (`opsmill/infrahub-solution-ai-dc` vs `opsmill/infrahub-enterprise-solution-ai-dc`) — the
compose file and `Dockerfile` only read the variables it exports. Every Compose-driving task also
accepts `--edition`. `docker-compose.yml` is vendored per edition; the tasks fail loud rather than
run a mixed stack when it does not match.

### Agentic Layout

- `.agents/skills/` — vendor-neutral source of truth for AI agent skills: the `infrahub-*` skills (installed from `opsmill/infrahub-skills`, pinned in `skills-lock.json`) and the `speckit-*` skills
- `.claude/skills` — committed symlink view of `.agents/skills` for Claude Code discovery
- `.mcp.json` — committed MCP client config for the `infrahub-mcp` sidecar in `docker-compose.override.yml`: how agents reach live Infrahub data (`mcp__infrahub__*` tools; token from `INFRAHUB_API_TOKEN`)
- `.specify/` — spec-kit workflow engine (constitution, templates, scripts)
- `dev/` — human-facing reference: `adr/` (MADR decision records), `guides/`, `guidelines/`, `knowledge/`

## Code Style

- Python >=3.11, target 3.12
- Ruff with `select = ["ALL"]`, key ignores: D (docstrings), CPY (copyright), PT (pytest), FBT, PLR
- Line length: 120 (ruff), 150 (pycodestyle max)
- mypy strict mode (`disallow_untyped_defs = true`)
- Double quotes, 4-space indent
- Async/await throughout generators and transforms
- yamllint with 140 char line length

## Key Patterns

- Generators inherit `InfrahubGenerator` + `GeneratorMixin`, implement `async def generate(self, data: dict)`
- Transforms inherit `InfrahubTransform`, implement `transform()` returning artifact content
- Checksum calculation uses sorted related object IDs for idempotent change detection
- GraphQL queries live alongside their Python files as `.gql` files
- Query response models (`*_query.py`) are generated — do not edit manually
