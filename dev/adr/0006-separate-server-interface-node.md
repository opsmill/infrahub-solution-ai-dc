# Server ports are their own node kind, not NetworkInterface

A server's port is a `ServerInterface` (namespace `Server`, name `Interface`) that inherits only the
`NetworkEndpoint` generic — the cabling contract (`link`), which is all a `NetworkLink` needs to join a
server port to a leaf port. `NetworkInterface` is untouched: it keeps a **required** `device`, a
single-column owner, and a `human_friendly_id` that always resolves.

## Considered Options

- **A separate `ServerInterface` kind (chosen)** — each kind has exactly one owner, so uniqueness is
  `[server, name__value]` on one side and `[device, name__value]` on the other; both `human_friendly_id`s
  resolve, so the generator upserts the server port by identity instead of hand-rolling a lookup.
- **Reuse `NetworkInterface` for both (previous)** — no new kind, but the owner had to become two optional
  `Parent` relationships with "exactly one is set" enforced in generator code rather than the schema; the
  uniqueness constraint had to key on both owners at once (`[device, server, name__value]`), and the
  `human_friendly_id` (`device__hostname__value`) did not resolve for a server port at all.

## Consequences

- `ServerInterface` carries its own `name`, `status`, `role` (`production`/`management`), `description` and
  `mtu`. Its `role` choices are the server's own concern — the leaf-facing port keeps `NetworkInterface`'s
  `role: server`, which is what the generator selects on and the startup-config templates render.
- The two ends of a p2p link are now different kinds, so `addressing.assign_ip_address_to_interface`
  re-fetches through `node.get_kind()` instead of a hard-coded kind.
- `cabling_plan.py` reports fabric cabling only: it walks `endpoint.peer.device`, which a `ServerInterface`
  has no equivalent of, so server attachment links are skipped by an explicit typename check rather than
  crashing on a null owner.
- `NetworkServer.interfaces` peers `ServerInterface`; field names are unchanged, so the
  `... on NetworkServer { interfaces { ip_address } }` fragment and the eBGP neighbor blocks in the vendor
  templates are unaffected.
- `computed_interface_description` still assumes every link endpoint has a `device`. Its computed attribute
  is commented out in the schema, so this is latent, not broken.
