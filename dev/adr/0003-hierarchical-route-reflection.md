# Hierarchical iBGP route reflection, leaf-only VTEPs

> **Partially superseded by [ADR-0005](0005-stored-bgp-sessions-and-rr-flag.md)**: the RR topology below
> still stands, but sessions and the route-reflector role are now stored as data (populated by the
> generators) instead of derived at render time.

The iBGP L2VPN-EVPN overlay uses hierarchical route reflection matching the 5-stage Clos: leafs are RR
clients of their pod's spines; spines reflect for those leafs *and* are clients of the super-spines; the
super-spines are the top-level reflectors. Only leaf switches are VTEPs — spines and super-spines run the
EVPN control plane but never encapsulate VXLAN. We chose this because it aligns sessions with the physical
topology (each leaf holds only a handful of sessions), scales for a large fabric, and matches the
"large-scale AI DC" framing.

## Considered Options

- **Hierarchical RR (chosen)** — spines + super-spines both reflect; canonical 5-stage design.
- **Super-spines-only RR** — rejected: every leaf peers multihop to every super-spine (more sessions per
  leaf) and the spine tier carries no EVPN; simpler to render but less representative of real large fabrics.

## Consequences

- ~~The route-reflector-client relationship is derived from tier ordering in the template (super-spine →
  spine → leaf), so no `route_reflector` attribute is stored on devices.~~ Superseded by ADR-0005: the
  tier ordering now drives generator-populated `NetworkBGPSession.rr_client` flags and a stored
  `NetworkDevice.route_reflector` boolean.
- Spines render both client config (toward super-spines) and RR-client config (toward leafs).
- VTEP state (NVE interface, VTEP loopback) exists only on leafs.
