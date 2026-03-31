![Infrahub Logo](https://assets-global.website-files.com/657aff4a26dd8afbab24944b/657b0e0678f7fd35ce130776_Logo%20INFRAHUB.svg)

<p align="center">
<a href="https://www.linkedin.com/company/opsmill">
<img src="https://img.shields.io/badge/linkedin-blue?logo=LinkedIn" alt="LinkedIn badge"/>
</a>
<a href="https://discord.gg/opsmill">
<img src="https://img.shields.io/badge/Discord-7289DA?&logo=discord&logoColor=white" alt="Discord badge"/>
</a>
</p>

# AI/DC Solution

The AI/DC Solution is a reference implementation showing how to use [Infrahub](https://github.com/opsmill/infrahub) to automate the build and ongoing operation of large-scale AI data center fabrics. It is fully functional and positioned as a demo and reference implementation — the patterns it demonstrates are already in production use by Infrahub customers.

---

## What you can do with it

- **Build a complete data center fabric from minimal inputs** — define a spine count, pod count, and rack layout; Infrahub generates all devices, IP allocations, and a cabling plan
- **Extend infrastructure without rebuilding it** — add a rack or pod and only the affected layer re-runs; the rest of the fabric is unchanged
- **Run parallel builds at scale** — trigger once at the fabric level; all pods and racks generate automatically and simultaneously
- **Track what was built and why** — design intent and implementation are stored together in Infrahub, linked explicitly, so day-two changes are surgical rather than full rebuilds
- **Study and adapt the Generator patterns** — modular Generators with checksum-triggered signaling, prerequisite validation, IP space delegation, and idempotent upserts, all documented and adaptable to other infrastructure domains

---

## Who this is for

**Evaluator / Learner:** You want to see design-driven automation in action. Clone the repo, run the demo, and watch Generators fire, devices appear, and IP pools allocate — all from minimal inputs. No prior Infrahub experience or code modifications required.

> Start with [Quick Start](#quick-start), then go to the [Demo Guide](docs/docs/solution-ai-dc/demo-guide.mdx).

**Advanced Implementer:** You are already working with Infrahub and want a production-quality reference for modular Generator patterns: checksum-triggered signaling, self-protecting Generators with prerequisite validation, IP space delegation across layers, and idempotent upserts.

> Go straight to the [Generator Patterns](docs/docs/solution-ai-dc/generator-patterns.mdx) and dig into the code.

---

## Prerequisites

- Python 3.11+ and [uv](https://docs.astral.sh/uv/)
- Docker and Docker Compose (v2)
- Git

---

## Quick start

```bash
git clone git@github.com:opsmill/solution-ai-dc.git
cd solution-ai-dc

# Install dependencies and start the environment
uv sync --all-packages
uv run inv start

# Load demo data
uv run inv load

# Wait for repository sync
uv run infrahubctl repository list

# Load trigger rules (after repository sync completes)
cp objects/20_triggers.yml.save triggers.yml
uv run infrahubctl object load triggers.yml
```

Then in the Infrahub UI: navigate to **Actions > Generator Definitions > generate-fabric**, click **Run**, and select a target fabric.

> For a detailed walkthrough of every step, see [Installation & Setup](docs/docs/solution-ai-dc/installation-setup.mdx).

---

## What you will see

When you run the demo:

1. You trigger **FabricGenerator** for a fabric (e.g., Fabric-A: 6 super spines, 3 pods)
2. FabricGenerator allocates the fabric-level IP pool, creates super spine switches, then writes a checksum to each child Pod
3. That checksum triggers **PodGenerator** for every pod simultaneously — they run in parallel
4. Each PodGenerator allocates pod-level IP space, creates spine switches, connects them to the super spines, then writes a checksum to each child Rack
5. Those checksums trigger **RackGenerator** for every rack across every pod — all run in parallel
6. Each RackGenerator creates leaf switches and connects them to the pod's spines

You trigger once. Everything else runs automatically. Devices, IP allocations, and the cabling plan are all visible and queryable in Infrahub.

---

## What's included

The solution is a self-contained repository with everything needed to run the demo and study the implementation:

- **Schemas** — a complete data model covering logical design (Fabric, Pod), physical location (Hall, Rack), devices, IPAM, and the GeneratorTarget generic that enables trigger-based signaling
- **Generators** — FabricGenerator, PodGenerator, and RackGenerator, each scoped to a single layer, with `.infrahub.yml` wiring definitions, targets, queries, and trigger rules
- **Transforms and artifacts** — startup configuration (Jinja2), cabling plan (Python), and computed interface descriptions
- **Demo data** — two pre-configured fabrics (Fabric-A: 6 super spines, 3 pods; Fabric-B: 4 super spines, 3 pods with Dell equipment), plus device types, IPAM pools, interface profiles, and device templates
- **Trigger rules** — `CoreNodeTriggerRule` and `CoreGeneratorAction` definitions driving the modular execution
- **Infrastructure** — Dockerfile, Docker Compose, and invoke tasks (`inv start`, `inv load`) for local setup

---

## Documentation

| Topic                       | Resource                                                                                                                                     |
|-----------------------------|--------------------------------------------------------------------------------------------------------------------------------------|
| **Run the demo**            | [Demo Guide](docs/docs/solution-ai-dc/demo-guide.mdx)                                                                                |
| **Set up the environment**  | [Installation & Setup](docs/docs/solution-ai-dc/installation-setup.mdx)                                                              |
| **Understand the concepts** | [Design-Driven Automation](docs/docs/solution-ai-dc/design-driven-automation.mdx)                                                    |
| **Learn the architecture**  | [Modular Generator Architecture](docs/docs/solution-ai-dc/modular-generator-architecture.mdx)                                        |
| **Study the code patterns** | [Generator Patterns](docs/docs/solution-ai-dc/generator-patterns.mdx)                                                                |
| **Infrahub core docs**      | [Generators](https://docs.infrahub.app/topics/generator) · [Modular Generators](https://docs.infrahub.app/topics/modular-generators) |

---

## About Infrahub

[Infrahub](https://github.com/opsmill/infrahub) is an open source infrastructure data management and automation platform (AGPLv3), developed by [OpsMill](https://opsmill.com). It gives infrastructure and network teams a unified, schema-driven source of truth for all infrastructure data — devices, topology, IP space, configuration — with built-in version control, a Generator framework for automation, and native integrations with Git, Ansible, Terraform, and CI/CD pipelines.
