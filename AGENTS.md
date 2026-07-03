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

### Core Library (`src/infrahub_bunlde_dc_ai/`)

- `generator.py` — `GeneratorMixin` providing checksum calculation for change detection
- `protocols.py` — Auto-generated typed node definitions from Infrahub schemas
- `cabling.py` — Cabling plan algorithms
- `addressing.py` — IP addressing utilities
- `sorting.py` — Device/interface sorting utilities

### Generators (`generators/`)

Three generators that create infrastructure objects via `InfrahubGenerator` + `GeneratorMixin`:

- `generate_fabric.py` — Creates super-spine devices for a fabric
- `generate_pod.py` — Creates spine/leaf devices for a pod
- `generate_rack.py` — Creates devices for a rack

Each generator has a paired `.gql` query file and a `*_query.py` generated query model file. Configured in `.infrahub.yml`.

### Transforms (`transforms/`)

- `cabling_plan.py` — CSV cabling plan generation (`InfrahubTransform`)
- `computed_interface_description.py` — Interface description transform
- `templates/startup_config.j2` — Jinja2 template for device startup configs

### Data Files

- `schemas/` — Infrahub schema definitions (YAML)
- `objects/` — Object data files loaded in numbered order (01-20)
- `menus/` — UI menu definitions
- `.infrahub.yml` — Registers all generators, transforms, queries, and artifact definitions

### Agentic Layout

- `.agents/skills/` — vendor-neutral source of truth for AI agent skills: the `infrahub-*` skills (installed from `opsmill/infrahub-skills`, pinned in `skills-lock.json`) and the `speckit-*` skills
- `.claude/skills` — committed symlink view of `.agents/skills` for Claude Code discovery
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
