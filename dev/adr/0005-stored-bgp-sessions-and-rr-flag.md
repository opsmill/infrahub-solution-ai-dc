# BGP sessions and route-reflector role stored as data

Supersedes the "derived at render time" consequences of [ADR-0003](0003-hierarchical-route-reflection.md).
The hierarchical route-reflection topology itself (leafs → spines → super-spines, leaf-only VTEPs) is
unchanged.

The iBGP L2VPN-EVPN control plane is now modeled as data: each device owns directional
`NetworkBGPSession` objects (peer, local/remote AS, address family, and an `rr_client` flag meaning
"render `route-reflector-client` toward this peer"), and each device carries a `route_reflector` boolean
(true on spines and super-spines). The fabric/pod/rack generators populate both when they cable the
tiers — sessions follow the actual cabling plan, not an assumed full mesh — and the startup-config
transform renders `router bgp` neighbors directly from the sessions.

## Considered Options

- **Stored sessions + stored RR flag (chosen)** — the control plane is queryable data in the system of
  record, consistent with FR-011; the eBGP future (per-session `remote_as`) becomes a data change, not a
  template rewrite; the template stops re-deriving topology through `interfaces → link → endpoints`.
- **Render-time derivation (previous, ADR-0003)** — no extra objects, but the control plane is invisible
  to queries, the tier policy lives in Jinja, and eBGP would require template surgery.

## Consequences

- `NetworkBGPSession` is directional: one object per device per peer; an adjacency yields two sessions.
  The tier policy (who reflects for whom) lives in `overlay.rr_client()` and is applied **once, at
  population time** by the generators.
- A device-level `route_reflector` boolean alone cannot express hierarchical RR (a spine is both a
  reflector and a client), so rendering is driven by the per-session `rr_client` flag; the device flag is
  the operator-facing marker.
- The template renders neighbors sorted by peer hostname — deterministic artifacts, but a one-time
  reordering relative to the previous interface-derived order.
- Devices built before this change render an empty `router bgp` neighbor list until their generators are
  re-run to materialize sessions.
