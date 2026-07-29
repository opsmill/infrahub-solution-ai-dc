# Quickstart: Validating the Server Service

End-to-end validation that connecting a server works. Assumes the implementation (per `plan.md`,
`data-model.md`, `contracts/`) is in place on a fabric already built by the existing generators. Commands use
the project's `invoke` tasks (`inv`) and `uv`.

## Prerequisites

- `uv sync --all-packages` has run; Docker available.
- Familiarity with the existing build (`inv start`, `inv load`) — see `AGENTS.md`.
- A fabric with racks and at least one Tenant → VRF (→ Segment, for the L2 case) already exists (the seed in
  `objects/12_overlay.yml`).

## 1. Static checks

```bash
inv lint        # yamllint + ruff (ALL) + mypy (strict) — schema YAML and new Python must pass
inv test        # pytest — new unit tests must pass:
                #   least-utilized rack selection + tie-break, free server-port selection,
                #   server-ASN / /31 pairing (correct remote_as each side), and every fail-loud path
```

**Expected**: lint clean; all unit tests green.

## 2. Schema converges

```bash
inv load-schema     # loads schemas/ incl. new server.yml + edits
```

**Expected**: schema loads without error; new kinds `NetworkServerService`, `NetworkServer`, and generic
`NetworkBGPPeer` exist; `NetworkBGPSession.device`/`peer_device` accept a `NetworkBGPPeer`;
`IpamIPPrefix.role` includes `server_p2p`; `NetworkPod.server_prefix_pool` exists; `NetworkInterface` has an
optional `server` owner. `NetworkServer` is **not** a `CoreArtifactTarget`.

## 3. Full build + server seed

```bash
inv load            # schema → menu → objects (incl. 07_pools Server ASN Pool, 13_servers seed) → repository
inv start           # bring up the stack; generators run via triggers
```

**Expected after generators settle**: the per-Pod `server_prefix_pool` exists on each pod (created by the
PodGenerator), and the global `Server ASN Pool` is present.

## 4. L3 server — the core proof (User Story 1 / P1)

Create an L3 `NetworkServerService` in a VRF with **no** rack/port (or use the `13_servers.yml` seed), let
the ServerGenerator run, then verify:

- A `NetworkServer` exists, cabled (via a `NetworkLink`) to a leaf's `role:server` port.
- A /31 (role `server_p2p`) is assigned on **both** ends (leaf rack-side + server).
- The server has an allocated private `asn` (from the global pool).
- Two `NetworkBGPSession`s exist, `address_family: ipv4_unicast`, `rr_client: false`:
  the **leaf** session `remote_as == server.asn`, the **server** session `remote_as == fabric.overlay_asn`.

Verify via the Infrahub UI / GraphQL (or the Infrahub MCP tools): query the `NetworkServer` and its
`interfaces`/`bgp_sessions`; query the leaf and confirm the new `role:server` port has the /31 and a session.

**(SC-001)** All of the above from a single service object with zero extra operator input.

## 5. Rendered leaf config (User Story 1 / SC-004)

Open the leaf's `Startup configuration` artifact and confirm (per `contracts/config-artifact.md`):

- the server-facing interface renders `no switchport` + the /31 `ip address`;
- `router bgp` has an `ipv4_unicast` eBGP neighbor at the **server's /31 address** with
  `remote-as <server asn>`, **no** `update-source Loopback0`, **no** `route-reflector-client`, activated
  under the ipv4-unicast address family.

Confirm **no server config artifact** exists (the `NetworkServer` is not an artifact target).

## 6. Idempotency (SC-003)

Re-run the generator on the unchanged service (e.g. touch nothing and let a re-trigger fire, or re-run
`infrahubctl generator generate-server`).

**Expected**: **empty diff** — no new server, link, IP, ASN, or session; unrelated leaves' artifacts
byte-identical.

## 7. L2 server (User Story 2 / P2)

Create an L2 `NetworkServerService` in a VRF, naming an existing Segment (rack/ports blank).

**Expected**: a `NetworkServer` cabled to a leaf; that leaf's **Rack now appears in the Segment's `racks`**
placement; **no** `NetworkBGPSession` and **no** /31 were created (FR-006). (Whether the segment is then
materialized onto the leaf is the OverlayGenerator's job — see research SD8.)

## 8. Explicit placement, honor-or-fail (User Story 3 / P3)

- **Honor**: create a service naming a valid free Rack + `role:server` leaf port → exactly that rack/port is
  used.
- **Fail loud**: create a service naming an **occupied** or wrong-role leaf port → the generator errors
  clearly and **creates no partial objects** (SC-002). Repeat for: no eligible rack/port in the Fabric,
  Segment not in the service's VRF, pool exhaustion, and a contradictory L3+Segment request.

## Success mapping

| Step | Validates |
|------|-----------|
| 1–2  | Lint/tests green, schema convergence, server kept out of the artifact path |
| 3–5  | L3 auto-connect: link + /31 both ends + eBGP both sides + rendered leaf config (US1, FR-001/003/005/009, SC-001/SC-004) |
| 6    | Idempotent re-run (FR-008, SC-003) |
| 7    | L2 Segment placement, no BGP/IP (US2, FR-006) |
| 8    | Explicit placement honored; fail-loud on every invalid path (US3, FR-002/004, SC-002) |
