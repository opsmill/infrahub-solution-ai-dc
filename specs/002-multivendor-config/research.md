# Phase 0 Research: Multivendor Per-Vendor Configuration

All spec decisions were resolved with the user during the grilling session; this file records each decision
with rationale and the validated Infrahub/SDK mechanics that make it implementable. No `NEEDS CLARIFICATION`
markers remain.

## D1 — Group shape: nested `devices → {vendor}_devices`

- **Decision**: Add `cisco_devices`, `arista_devices`, `dell_devices` as `CoreStandardGroup`s that are
  children of the existing `devices` group.
- **Rationale**: The user wants an organizational tree; `devices` stays the union/parent, vendor groups are
  the artifact-targeting leaves.
- **Validated mechanic**: `CoreGroup` (parent of `CoreStandardGroup`) natively exposes `parent`, `children`,
  and `members` (`.venv/.../infrahub_sdk/protocols.py:143`). Nesting is therefore supported by the core model
  with no schema change.
- **Key caveat**: Nesting is **organizational only** — a device is *not* implicitly a member of a child
  group. Membership must be stamped explicitly (see D2). This is why "nested groups" and "generator resolves
  vendor" are both required, not alternatives.
- **Alternatives considered**: (a) flat vendor groups with no parent — rejected, loses the union view; (b)
  rely on artifact targeting cascading parent→child — rejected as unverified and unnecessary given D2.

## D2 — Membership mechanism: the generator resolves the vendor

- **Decision**: Each topology generator resolves the manufacturer of each device it creates and adds the
  device to both `devices` and its `{vendor}_devices` child group. The generator is **not** forked per vendor.
- **Rationale**: The generator is the single point that creates devices; membership belongs there.
- **Validated mechanic**: `NetworkDevice.device_type` (`schemas/device.yml:97`, identifier
  `device__device_type`) → `NetworkDeviceType.manufacturer` (`schemas/device.yml:50`) →
  `OrganizationManufacturer.name`. The manufacturer is inherited onto the device from its object template's
  `device_type` (e.g. template `dell-s5232f-on-leaf-switch-compute` sets `device_type: ["Dell", ...]`).
- **Implementation path**: The generators already re-fetch each freshly created device (e.g.
  `generate_fabric.py:65`, `generate_rack.py:165`) to assign the loopback IP. Extend that re-fetch with
  `include=["device_type"]`, resolve the manufacturer name, map to `f"{name.lower()}_devices"`, and add the
  membership on the device before saving. Read via the SDK — **no generator `.gql` change** needed.
- **Group-name mapping**: `Manufacturer.name` ∈ {`Cisco`, `Arista`, `Dell`} → `cisco_devices`,
  `arista_devices`, `dell_devices` (lowercased name + `_devices`).
- **Alternatives considered**: resolving the manufacturer from the object template at query time (fewer
  writes, but requires template-schema introspection through the generator query) — kept as a possible
  optimization, not the primary path, because resolving from the created device is simpler and robust.

## D3 — Fail loudly on an unresolvable vendor

- **Decision**: If a device's manufacturer cannot be resolved (no `device_type`, or a manufacturer with no
  vendor group), the generator raises a clear error naming the device; it does not skip or fall back.
- **Rationale**: Treats "every device declares a vendor" as an invariant for this reference solution; data
  gaps must surface, not silently drop config.
- **Consequence**: The five vendor-less templates and the vendor-less super-spine in Fabric-A must be fixed
  as part of this work (see D5/D6) so the shipped dataset never trips this error.
- **Shared helper**: `src/infrahub_solution_ai_dc/vendors.py` centralizes the resolve-or-raise so all three
  generators behave identically.

## D4 — Split scope: startup config only

- **Decision**: Only the startup-config artifact is split per vendor. `cabling_plan` (targets `fabrics`, CSV)
  and `computed_interface_description` (vendor-neutral text) are unchanged.
- **Rationale**: Smallest sharp slice that proves the pattern; the other artifacts have no vendor divergence
  yet.

## D5 — Templates: add the two missing storage-leaf templates

- **Decision**: Add `cisco-93400ld-h1-leaf-switch-storage` and `arista-7050x4-48y-4df-leaf-switch-storage`,
  reusing the existing Cisco/Arista leaf device types, mirroring the Dell storage leaf's port-profile split
  (spine-facing uplinks + compute-facing access ports).
- **Rationale**: Fabric-A (Cisco) and Fabric-B (Arista) both contain storage racks, but Cisco/Arista had only
  compute-leaf templates. Adding them keeps every fabric's rack topology identical and all three vendors
  symmetric.
- **Reference**: `objects/06_device_template.yml` — `dell-s5232f-on-leaf-switch-storage` (spine-facing
  `Ethernet1/1/[1-16]` + compute-facing `Ethernet1/1/[17-34]`).

## D6 — Dataset re-vendoring: A→Cisco, B→Arista, C(new)→Dell

- **Decision**: Fabric-A (currently vendor-less generic) → Cisco; Fabric-B (currently Dell) → Arista; add a
  new Fabric-C on Dell that mirrors today's Fabric-B topology. Remove the five generic templates once nothing
  references them.
- **Rationale**: Gives three clean single-vendor fabrics to choose from; "relocates" the proven Dell demo to
  C and frees B for Arista. Grep confirmed the five generic templates are referenced only by Fabric-A/B data.
- **Validated mechanic**: `generate_fabric.py:113` (`allocate_resource_pools`) carves a per-fabric `/16` from
  `FabricSupernetPool` (10.0.0.0/8) keyed by fabric id, and an ASN from the pool — so **Fabric-C needs no
  manual addressing/ASN**. The `/8 → /16` supernet leaves ample room for a third fabric.

## D7 — Artifact registration: three transforms, three artifact definitions

- **Decision**: Replace the single `device_startup_config` jinja2 transform and `startup_configuration`
  artifact (targets `devices`) with three transforms (one per vendor template) and three artifact definitions
  (`targets: cisco_devices | arista_devices | dell_devices`). All three transforms reuse the existing
  `network_device_startup_config` GraphQL query.
- **Rationale**: A `jinja2_transform` binds exactly one template; per-vendor templates therefore need one
  transform each, and one artifact definition each to bind a transform to a target group.
- **One-config invariant**: No artifact targets `devices` after the split, so a device (member of both
  `devices` and one vendor group) renders exactly one config. Infrahub evaluates artifact definitions against
  their target group's direct members — no trigger-file change is needed for artifacts.

## Cross-cutting: no schema change

Confirmed no schema edits are required — vendor groups are core `CoreStandardGroup`; the vendor is read from
the existing `device_type/manufacturer` relationship. Therefore `src/infrahub_solution_ai_dc/protocols.py` is
**not** regenerated, and the AGENTS.md "GraphQL/schema change" governance gate is **not** crossed (the
generator queries are unchanged; only `.infrahub.yml` registration and object data change).
