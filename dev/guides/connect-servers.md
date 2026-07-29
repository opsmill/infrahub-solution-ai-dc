# Connect servers (the Server service)

How an operator attaches a workload to the fabric with one design object. Feature spec:
`specs/003-server-service/`.

## What it does

The fabric generators build super-spines, spines, and leaves, but nothing connects the servers the
fabric exists to serve. The **Server service** (`NetworkServerService`) closes that gap: it records the
*intent* to connect a server, and a standalone `ServerGenerator` materializes everything else.

An operator creates one `NetworkServerService` capturing:

- **layer** — `l2` or `l3`;
- **VRF** — the tenancy the server belongs to (Tenant is implied by the VRF);
- optionally a target **Rack** and/or **leaf port** (explicit placement);
- for **L2**, a **Segment** under that VRF.

From that, the generator produces a `NetworkServer` (an *implementation object*, distinct from a
`NetworkDevice`) plus its interfaces and cabling. The service targets the `server_services` group and is
re-run on checksum change, like every other generator.

## Design vs. implementation

- **Design object**: `NetworkServerService` — the request, owned by the operator.
- **Implementation object**: `NetworkServer` + its `ServerInterface` ports + `NetworkLink` + IP/ASN/BGP
  allocations,
  produced by the generator. The `NetworkServer` is **never** swept into `devices`/`{vendor}_devices`
  groups and is **not** a `CoreArtifactTarget` — it renders no startup-config of its own; only the leaf
  side is materialized.

See `CONTEXT.md` for the design-object / implementation-object / generator vocabulary.

## Placement

When the service names no Rack/port, the generator auto-selects:

- the **least-utilized Rack** in the VRF's Fabric (fewest servers, deterministic tie-break);
- the **lowest-numbered free leaf port** with the `server` role.

When the service names a Rack and/or port, they are **honored exactly** if valid, and otherwise **fail
loud** with no partial objects (occupied/wrong-role port, rack with no free port, port not on a leaf of
the rack, rack outside the VRF's Fabric). Last-free-port contention is deterministic: at most one writer
wins, the loser's `save` fails rather than double-allocating.

## L3 vs. L2

- **L3** (BGP-speaking, e.g. a Kubernetes/Cilium worker): allocate a `server_p2p` **/31** on both ends
  (rack-side address on the leaf), allocate a private **server ASN** (32-bit private pool, distinct from
  the 16-bit overlay ASN), and upsert a paired **eBGP** `ipv4_unicast` session on the leaf
  (`remote_as = server.asn`) and the server (`remote_as = fabric.overlay_asn`), `rr_client = false`. The
  leaf startup-config renders the routed interface, the /31, and the eBGP neighbor.
- **L2** (bridged host): cable the server to a leaf and add that leaf's Rack to the named Segment's
  `racks` placement. **No** fabric-side BGP and **no** /31/ASN. Whether the Segment is then materialized
  onto the leaf is the OverlayGenerator's job (research open item SD8; v1 keeps it a separate step).

## Idempotency

Re-running on an unchanged service is an empty diff: deterministic server name, upsert-by-name BGP
sessions, a stable /31 identifier, edge-scoped `add_relationships`, ASN allocated only if unset, and
`update_group_context=False`. The Rack/Pod generator checksums **exclude** the server-side writes (leaf
`bgp_sessions`, server-facing interface/link) so a server connection does not re-trigger the physical
cascade.

## Related decisions

- [ADR-0002](../adr/0002-standalone-overlay-generator.md) — a standalone generator beside the physical
  cascade; the `ServerGenerator` follows the same pattern for a distinct, orthogonal lifecycle.
- [ADR-0004](../adr/0004-overlay-trigger-via-materialized-placement.md) — effects reach device configs
  via materialized placement, not the physical cascade; hence the checksum exclusion above.
- [ADR-0005](../adr/0005-stored-bgp-sessions-and-rr-flag.md) — BGP sessions and the RR flag are stored as
  data; leaf↔server eBGP sessions reuse that model with `address_family: ipv4_unicast`, `rr_client: false`.
- [CONTEXT.md](../../CONTEXT.md) — domain language (design/implementation object, generator, vendor group).

## Try it

Follow `specs/003-server-service/quickstart.md` (§1 static checks, §2 schema convergence, §3 full build +
seed, §4–6 L3 proof + rendered config + idempotency, §7 L2, §8 explicit placement). Seed data lives in
`objects/13_servers.yml` (`cilium-worker-1` L3, `web-host-1` L2).
