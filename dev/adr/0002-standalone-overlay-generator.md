# Overlay tenancy uses a standalone OverlayGenerator beside the physical cascade

Tenant → VRF → Segment is a first-class design dimension with its own dedicated OverlayGenerator (triggered
by `NetworkTenant` checksum), running *beside* the Fabric → Pod → Rack generator cascade rather than inside
it. The physical generators get only small extensions (ASN stamping, VTEP loopback) because those are
intrinsic to building devices. We chose this because tenancy is orthogonal to the physical hierarchy — a
Tenant is not "below" a Rack — and has its own lifecycle (added/changed independently of topology), so it
deserves its own generator and its own scoped day-two workflow, symmetric with "add a rack".

## Considered Options

- **Standalone OverlayGenerator (chosen)** — one generator owns one concern, triggered by its own design
  object.
- **Fold overlay into the Rack generator** — rejected: conflates orthogonal lifecycles and forces a fabric
  rebuild to change tenant services.

## Consequences

- A new generator + trigger rule + GraphQL query, registered in `.infrahub.yml`.
- The overlay's effect on per-device config is propagated via materialized placement (see ADR-0004), not by
  the physical cascade.
