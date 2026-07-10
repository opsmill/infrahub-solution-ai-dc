# Overlay changes reach device configs via generator-materialized placement

When a Tenant/Segment changes, the affected leafs' startup-config artifacts must regenerate. We do this by
having the OverlayGenerator **materialize a `Device ↔ Segment` relationship** onto the carrying leafs (from
the optional `Segment ↔ Rack` placement intent; empty placement ⇒ every leaf in the fabric). Because the
leaf Devices then change, their artifacts regenerate through the existing "device changed → artifact
regenerates" path — the same checksum-driven cascade the solution already uses. We chose this over filtering
all fabric segments at render time plus a group artifact-regeneration trigger, because it reuses the
solution's established cascade pattern and keeps the per-device transform query simple (`device.segments`).

## Considered Options

- **Materialized placement (chosen, "Design Y")** — generator writes Device↔Segment; artifact regen rides
  the device-change path.
- **Render-time filtering + group trigger ("Design X")** — rejected: relies on a less-proven "regenerate
  artifacts for a device group" action and pushes placement logic into the template.

## Consequences

- Placement intent (`Segment ↔ Rack`) is separate from materialized state (`Device ↔ Segment`), mirroring
  the design-vs-implementation split.
- Overlay relationships must be **excluded** from the Rack/Pod generator checksums to avoid a re-trigger
  loop when the OverlayGenerator writes to leaf devices.
