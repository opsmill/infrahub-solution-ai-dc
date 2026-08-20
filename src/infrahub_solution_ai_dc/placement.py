"""Where a server attaches to the fabric — choosing a placement, and releasing the one it leaves.

Placement is the part of the Server service with the most invariants and the only destructive step in
the feature, so it lives behind two methods: :meth:`ServerPlacement.resolve` decides where the server
goes, and :meth:`ServerPlacement.release` clears what a move supersedes. Everything between them is
private, because no caller has a reason to run half of a placement.

The input is a :class:`PlacementRequest` of plain ids rather than a parsed query node: the generator
reads its own response shape and hands over the four values that matter, the same split
``clusters.py`` uses. That is what lets the whole of placement — reuse, re-placement, explicit
honouring, reclaim, teardown — be tested without a generator.

**Reuse is the load-bearing case, not an optimisation.** ``rack`` and ``leaf_interface`` round-trip:
the operator may set them to request a placement, and ``ServerGenerator.record_placement`` writes back
whichever was resolved. So on a re-run they normally *equal* the materialized placement, and a run
that re-selected instead would pick a different port (a cabled one is no longer free), producing a
second ``NetworkLink`` on the server's single ``eth1`` — whose endpoint cardinality is 1, so the run
dies after the server has already been re-pointed. :meth:`ServerPlacement.resolve` returning the
existing placement is what makes the whole downstream chain idempotent, since every other upsert key
is derived from it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, NamedTuple

from .protocols import (
    IpamIPAddress,
    IpamIPPrefix,
    LocationRack,
    NetworkBGPSession,
    NetworkDevice,
    NetworkInterface,
    NetworkLink,
    NetworkPod,
    NetworkServer,
    ServerInterface,
)
from .servers import (
    peer_endpoint_id,
    placement_matches_request,
    port_is_free,
    select_free_server_port,
    select_least_utilized_rack,
    validate_explicit_port,
)

if TYPE_CHECKING:
    import logging

    from infrahub_sdk import InfrahubClient

#: The deterministic name of the server's own leaf-facing port. Placement finds an already-cabled
#: server through it; ``ServerGenerator.materialize_server_port`` creates it under the same name.
SERVER_PORT_NAME = "eth1"


def server_hostname(service_name: str) -> str:
    """The deterministic hostname a service's ``NetworkServer`` carries — the generator's upsert key.

    Placement needs it for two reads: recovering a server a previous run cabled but never linked back
    to the service, and deciding whether an occupied port holds *this* service's leftovers.
    """
    return f"server-{service_name}"


@dataclass(frozen=True)
class PlacementRequest:
    """What placement needs to know about one server service, as plain ids.

    ``requested_rack_id``/``requested_port_id`` are the round-trip ``rack``/``leaf_interface`` fields:
    absent on a service the operator left alone, set either because the operator asked for a placement
    or because a previous run wrote back the one it resolved. Placement cannot tell those two apart
    from the values alone, and does not need to — it compares them against what is actually cabled.
    """

    fabric_id: str
    server_hostname: str
    linked_server_id: str | None = None
    requested_rack_id: str | None = None
    requested_port_id: str | None = None


class ResolvedPlacement(NamedTuple):
    """Where the server goes, plus the leaf ports whose occupancy the run has to clear first.

    ``released_ports`` holds the server's previous port when the operator re-pointed the service, and
    the target port when it still carries leftovers (a stale address or a cable to this service's own
    server). Both at once is possible: a move onto a port that was itself left dirty. Empty for the
    common cases — a first placement or an unchanged re-run — which is what keeps those runs free of
    any destructive write.
    """

    rack: LocationRack
    leaf: NetworkDevice
    leaf_port: NetworkInterface
    released_ports: tuple[NetworkInterface, ...] = ()


class ServerPlacement:
    """Resolves and releases a server's attachment point. Holds no state between calls."""

    def __init__(self, client: InfrahubClient, logger: logging.Logger) -> None:
        self._client = client
        self._logger = logger

    async def resolve(self, request: PlacementRequest) -> ResolvedPlacement:
        """Resolve where the server goes — reused, re-placed, automatic, or explicit (US3/T036).

        **Reused** (the service's server is already cabled and ``rack``/``leaf_interface`` still name
        that placement): return it unchanged via :meth:`_existing_placement`. This is the idempotent
        path and, because those fields are written back, the path every re-run takes — see that method
        for why recomputing instead is not merely wasteful but guaranteed to fail.

        **Re-placed** (already cabled, but the operator re-pointed ``rack`` or ``leaf_interface``):
        resolve the new placement explicitly and report the old leaf port as ``released_port`` so
        ``ServerGenerator.generate`` tears the superseded cable down before laying the new one. Which field the
        operator actually moved decides what is honored: a changed port names its own rack, so a
        ``rack`` still holding the *written-back* previous value must not veto the move (and vice
        versa). Only a change to both is required to be self-consistent.

        Automatic (unplaced, and neither ``rack`` nor ``leaf_interface`` on the service): pick the
        least-utilized eligible rack in the fabric, then the lowest free ``role:server`` port among
        that rack's leaves.

        Explicit (unplaced, either provided): honor the request exactly via
        :meth:`_resolve_explicit`, failing loud on any invalid placement. All validation
        happens **before** any object is created, so a rejected request leaves no partial objects
        (FR-004/SC-002).
        """
        explicit_rack_id = request.requested_rack_id
        explicit_port_id = request.requested_port_id

        existing = await self._existing_placement(request)
        if existing is not None:
            rack, leaf, leaf_port = existing
            if placement_matches_request(
                placed_rack_id=rack.id,
                placed_port_id=leaf_port.id,
                requested_rack_id=explicit_rack_id,
                requested_port_id=explicit_port_id,
            ):
                self._logger.info(
                    f"Reusing placement: rack {rack.name.value}, leaf {leaf.hostname.value}, "
                    f"port {leaf_port.name.value}"
                )
                return ResolvedPlacement(rack, leaf, leaf_port)

            # Re-placement: honor only the side the operator moved, so the other side's written-back
            # value (which still describes the placement being left behind) cannot contradict it.
            port_moved = explicit_port_id is not None and explicit_port_id != leaf_port.id
            rack_moved = explicit_rack_id is not None and explicit_rack_id != rack.id

            new_rack, new_leaf, new_port = await self._resolve_explicit(
                explicit_rack_id if rack_moved else None,
                explicit_port_id if port_moved else None,
                request,
            )
            self._logger.info(
                f"Re-placing from rack {rack.name.value} port {leaf_port.name.value} to "
                f"rack {new_rack.name.value} leaf {new_leaf.hostname.value} port {new_port.name.value}"
            )
            # The port being left, plus the target if it too was already dirty.
            released = (leaf_port, *(() if port_is_free(new_port) else (new_port,)))
            return ResolvedPlacement(new_rack, new_leaf, new_port, released_ports=released)

        if explicit_rack_id is None and explicit_port_id is None:
            rack = await self._select_rack(request.fabric_id)
            leaf, leaf_port = await self._select_leaf_port(rack)
            released = ()
        else:
            rack, leaf, leaf_port = await self._resolve_explicit(explicit_rack_id, explicit_port_id, request)
            # An explicit port carrying this service's own leftovers (a manually deleted server) is
            # honored, but its stale cable/IP has to go before it can be re-used.
            released = () if port_is_free(leaf_port) else (leaf_port,)

        self._logger.info(f"Placement: rack {rack.name.value}, leaf {leaf.hostname.value}, port {leaf_port.name.value}")
        return ResolvedPlacement(rack, leaf, leaf_port, released_ports=released)

    async def _placed_server_id(self, request: PlacementRequest) -> str | None:
        """Return the id of this service's already-materialized server, or ``None`` if there is none.

        Prefers the ``service.server`` relationship the caller resolved and falls back to the hostname, so a
        server cabled by a run that never reached ``ServerGenerator.record_placement`` is still recognized.
        """
        if request.linked_server_id is not None:
            return request.linked_server_id

        servers = await self._client.filters(kind=NetworkServer, hostname__value=request.server_hostname)
        return servers[0].id if servers else None

    async def _existing_placement(
        self, request: PlacementRequest
    ) -> tuple[LocationRack, NetworkDevice, NetworkInterface] | None:
        """Recover the placement a previous run materialized, or ``None`` when the service is unplaced.

        Placement **must not** be recomputed for a service that already has a cabled server, and not
        just to save work: :func:`~infrahub_solution_ai_dc.servers.select_free_server_port` counts a port with a link as *not*
        free, so a re-run necessarily picks a *different* port. That yields a differently-named
        ``NetworkLink`` on the server's single ``eth1``, whose ``networkendpoint__networklink``
        cardinality is 1 — so the second link is rejected and the run dies *after*
        ``ServerGenerator.materialize_server`` has already re-pointed ``server.rack``. Reusing the placement is
        what makes the whole chain (server, port, link, /31, sessions) idempotent: every downstream
        upsert key is derived from it, including the ``/31`` allocation identifier (the port-id pair).

        Since ``ServerGenerator.record_placement`` writes the resolved placement back onto the service, this lookup
        is also what stops a re-run from re-entering the *explicit* path with the values it wrote there
        — where the now-cabled port would fail the "must be free" check on every run.

        The server is found through ``service.server`` when set, and otherwise by the deterministic
        hostname ``ServerGenerator.materialize_server`` assigns. That fallback matters: ``ServerGenerator.generate`` cables at
        step 4 but only points ``service.server`` at step 7, so a failure in between (an exhausted ASN
        pool, an unallocated ``overlay_asn``) leaves a cabled server the service does not reference —
        and keying reuse solely on the relationship would re-select a port and crash exactly as before.

        From there it walks server -> its ``eth1`` -> that port's link -> the link's far endpoint (the
        leaf port) -> its leaf -> its rack. Returns ``None`` at any missing step so a half-built server
        (created but never cabled) falls through to normal selection and gets finished rather than being
        reused in a broken state.
        """
        server_id = await self._placed_server_id(request)
        if server_id is None:
            return None

        server_ports = await self._client.filters(
            kind=ServerInterface,
            server__ids=[server_id],
            name__value=SERVER_PORT_NAME,
            include=["link"],
        )
        server_port = next((port for port in server_ports if port.link.id is not None), None)
        if server_port is None:
            return None

        link = await self._client.get(kind=NetworkLink, id=server_port.link.id, include=["endpoints"])
        leaf_port_id = peer_endpoint_id(
            [peer.id for peer in link.endpoints.peers if peer.id is not None], server_port.id
        )
        if leaf_port_id is None:
            return None

        leaf_port = await self._client.get(
            kind=NetworkInterface, id=leaf_port_id, include=["ip_address", "link", "device"]
        )
        if leaf_port.device.id is None:
            return None
        leaf = await self._client.get(kind=NetworkDevice, id=leaf_port.device.id, include=["rack"])
        if leaf.rack.id is None:
            return None
        rack = await self._client.get(kind=LocationRack, id=leaf.rack.id)
        return rack, leaf, leaf_port

    async def _resolve_explicit(
        self,
        explicit_rack_id: str | None,
        explicit_port_id: str | None,
        request: PlacementRequest,
    ) -> tuple[LocationRack, NetworkDevice, NetworkInterface]:
        """Honor an explicit ``rack``/``leaf_interface`` exactly, or fail loud (US3, FR-004/SC-002).

        Validation order (all reads, all before any write — a rejection leaves no partial objects):

        * an explicit rack must belong to the service's fabric;
        * a rack given without a port falls back to the lowest free ``role:server`` port on it;
        * an explicit port is re-fetched (the generator query omits ``ip_address``/``link``), its leaf
          resolved, and the chosen rack taken as the explicit rack or the port's leaf's rack;
        * the port must sit on a leaf of the chosen rack, and be ``role:server`` + free
          (:func:`validate_explicit_port`) — unless it is occupied by this service's own leftovers
          (:meth:`_port_is_reclaimable`), which the caller releases instead of refusing.

        ``request.server_hostname`` is used only for that ownership test.

        Last-free-port contention is **not** currently hard-enforced. Two services racing for the same
        port both pass this read-time check, and nothing on the write side stops the second racer:
        ``NetworkLink.endpoints`` carries no uniqueness constraint, and each server's link has a distinct
        name, so the loser's ``save`` silently re-points ``leaf_port.link`` instead of failing loud.
        Strict enforcement — a uniqueness constraint on the endpoint relationship, validated against a
        running stack — is a deferred follow-up (it needs the stack to verify) and is not attempted here.
        """
        fabric_rack_ids = await self._fabric_rack_ids(request.fabric_id)

        if explicit_rack_id is not None and explicit_rack_id not in fabric_rack_ids:
            msg = (
                f"Cannot honor explicit rack {explicit_rack_id!r}: it is not a rack of the "
                f"service's fabric {request.fabric_id!r}"
            )
            raise ValueError(msg)

        if explicit_port_id is None:
            # Rack given without a port: honor the rack, auto-pick its lowest free role:server port.
            assert explicit_rack_id is not None
            rack = await self._client.get(kind=LocationRack, id=explicit_rack_id)
            leaf, leaf_port = await self._select_leaf_port(rack)
            return rack, leaf, leaf_port

        # A port is named: re-fetch it fully (the query omits ip_address/link) and resolve its leaf.
        leaf_port = await self._client.get(
            kind=NetworkInterface, id=explicit_port_id, include=["ip_address", "link", "device"]
        )
        leaf_id = leaf_port.device.id
        if leaf_id is None:
            msg = (
                f"Cannot honor explicit leaf_interface {explicit_port_id!r}: it is not on any device (not a leaf port)"
            )
            raise ValueError(msg)
        leaf = await self._client.get(kind=NetworkDevice, id=leaf_id, include=["rack"])

        # Resolve the chosen rack: the explicit one (validated above) or the port's leaf's rack.
        rack_id = explicit_rack_id if explicit_rack_id is not None else leaf.rack.id
        if rack_id is None:
            msg = f"Cannot honor explicit leaf_interface {explicit_port_id!r}: its leaf {leaf_id!r} is in no rack"
            raise ValueError(msg)
        if explicit_rack_id is None and rack_id not in fabric_rack_ids:
            msg = (
                f"Cannot honor explicit leaf_interface {explicit_port_id!r}: its leaf's rack {rack_id!r} "
                f"is not in the service's fabric {request.fabric_id!r}"
            )
            raise ValueError(msg)
        rack = await self._client.get(kind=LocationRack, id=rack_id)

        # The port must sit on a leaf of the chosen rack (trivially true when the rack was derived).
        if leaf.rack.id != rack.id:
            msg = (
                f"Cannot honor explicit leaf_interface {leaf_port.name.value!r}: its leaf "
                f"{leaf.hostname.value!r} is not on rack {rack.name.value!r}"
            )
            raise ValueError(msg)

        # role:server + free (pure, unit-tested) — waiving "free" only for our own leftovers.
        reclaimable = not port_is_free(leaf_port) and await self._port_is_reclaimable(
            leaf_port, request.server_hostname
        )
        validate_explicit_port(leaf_port, rack.name.value, reclaimable=reclaimable)
        return rack, leaf, leaf_port

    async def _port_is_reclaimable(self, leaf_port: NetworkInterface, hostname: str) -> bool:
        """Return True when an occupied leaf port holds only *this* service's leftovers, safe to tear down.

        Deciding this is what keeps :meth:`_release_leaf_port`'s deletions safe: an explicitly requested
        port is reclaimed only when nothing live belongs to anyone else. The port qualifies when

        * it carries an IP but **no** link — an address a torn-down cable left behind, since nothing is
          attached to it;
        * its link has no far endpoint — a half-link left by a deleted server port;
        * its link's far endpoint is a ``ServerInterface`` owned by this service's server (or owned by
          no server at all).

        Everything else is somebody else's: a port cabled to another server, a link to a fabric-side
        ``NetworkInterface``, or a link with several far ends (not a point-to-point server cable, so
        guessing is unsafe). Those return False and :func:`validate_explicit_port` then fails loud.
        """
        if leaf_port.link.id is None:
            return True

        link = await self._client.get(kind=NetworkLink, id=leaf_port.link.id, include=["endpoints"])
        far_ends = [peer.id for peer in link.endpoints.peers if peer.id is not None and peer.id != leaf_port.id]
        if not far_ends:
            return True
        if len(far_ends) > 1:
            return False

        # ``filters`` (not ``get``) so a far end of another kind — or one already deleted — is an empty
        # result rather than a raise.
        server_ports = await self._client.filters(kind=ServerInterface, ids=far_ends, include=["server"])
        if not server_ports:
            fabric_ports = await self._client.filters(kind=NetworkInterface, ids=far_ends)
            return not fabric_ports  # nothing resolves at all => a dead cable; a fabric port => not ours
        owner_id = server_ports[0].server.id
        if owner_id is None:
            return True
        owner = await self._client.get(kind=NetworkServer, id=owner_id)
        return bool(owner.hostname.value == hostname)

    async def _fabric_rack_ids(self, fabric_id: str) -> set[str]:
        """Return the set of ``LocationRack`` ids belonging to the fabric (via its pods)."""
        pods = await self._client.filters(kind=NetworkPod, parent__ids=[fabric_id])
        pod_ids = [pod.id for pod in pods]
        racks = await self._client.filters(kind=LocationRack, pod__ids=pod_ids) if pod_ids else []
        return {rack.id for rack in racks}

    async def _select_rack(self, fabric_id: str) -> LocationRack:
        """Return the least-utilized rack in the fabric (fewest attached servers), fail-loud if none."""
        pods = await self._client.filters(kind=NetworkPod, parent__ids=[fabric_id])
        pod_ids = [pod.id for pod in pods]
        racks = await self._client.filters(kind=LocationRack, pod__ids=pod_ids) if pod_ids else []

        # Count servers only within this fabric's racks (O(fabric), not instance-wide); servers on
        # racks outside the fabric were discarded anyway, so scoping the query is behavior-preserving.
        fabric_rack_ids = [rack.id for rack in racks]
        servers = (
            await self._client.filters(kind=NetworkServer, rack__ids=fabric_rack_ids, include=["rack"])
            if fabric_rack_ids
            else []
        )
        server_counts: dict[str, int] = {}
        for existing in servers:
            rack_id = existing.rack.id
            if rack_id is not None:
                server_counts[rack_id] = server_counts.get(rack_id, 0) + 1

        rack = select_least_utilized_rack(racks, server_counts)
        if rack is None:
            msg = f"Cannot place server service: fabric {fabric_id} has no eligible rack"
            raise ValueError(msg)
        return rack

    async def _select_leaf_port(self, rack: LocationRack) -> tuple[NetworkDevice, NetworkInterface]:
        """Return the lowest free ``role:server`` port on a leaf of ``rack`` (fail-loud if none free)."""
        leaves = await self._client.filters(kind=NetworkDevice, role__value="leaf", rack__ids=[rack.id])
        if not leaves:
            msg = f"Cannot place server service: rack {rack.name.value} has no leaf switch"
            raise ValueError(msg)

        leaves_by_id = {leaf.id: leaf for leaf in leaves}
        server_ports = await self._client.filters(
            kind=NetworkInterface,
            device__ids=list(leaves_by_id),
            role__value="server",
            include=["ip_address", "link", "device"],
        )
        leaf_port = select_free_server_port(server_ports)
        if leaf_port is None:
            msg = f"Cannot place server service: no free role:server port on any leaf of rack {rack.name.value}"
            raise ValueError(msg)

        device_id = leaf_port.device.id
        assert device_id is not None
        return leaves_by_id[device_id], leaf_port

    async def release(self, placement: ResolvedPlacement, *, server_id: str, server_port_id: str) -> None:
        """Clear everything ``placement`` supersedes, so the server can be cabled to its new port.

        The generator's only destructive step, and a no-op unless :meth:`resolve` reported a
        released port — the operator moved the service, or the target port still carries this service's
        own leftovers. :meth:`_port_is_reclaimable` has already established that nothing being removed
        belongs to another server.

        Each released port is emptied by :meth:`_release_leaf_port`. The eBGP session pair is handled
        here instead, because it belongs to the *leaf* rather than the port: sessions are keyed by
        ``"{device}__{peer}"`` on ``(device, peer_device)``, so a move between ports of one leaf leaves
        them correct and :func:`~infrahub_solution_ai_dc.servers.upsert_ebgp_session` merely refreshes them, while a move to another leaf
        would otherwise strand the old pair, still rendering on the leaf the server just left. The
        rendered neighbor address needs no fixup either way — the template reads it from the peer's
        interface at render time rather than from the session.
        """
        stale_leaf_ids: set[str] = set()
        for released in placement.released_ports:
            leaf_id = await self._release_leaf_port(released, server_port_id)
            if leaf_id is not None and leaf_id != placement.leaf.id:
                stale_leaf_ids.add(leaf_id)

        for leaf_id in sorted(stale_leaf_ids):
            await self._delete_ebgp_pair(leaf_id, server_id)

    async def _release_leaf_port(self, old_leaf_port: NetworkInterface, server_port_id: str) -> str | None:
        """Empty one superseded leaf port and return the id of the leaf that owned it.

        The port is **detached first** and only then is what it pointed at deleted. The other order
        does not work: the port has to be saved anyway (to go back to ``inactive``), and a save re-sends
        every relationship the node still holds — so a cable or address deleted beforehand makes that
        save fail on a dangling reference. Clearing a to-one relationship with ``None`` is how the SDK
        emits an explicit unset.

        Then goes the ``NetworkLink`` — the server port's endpoint relationship is cardinality 1, so the
        new cable cannot coexist with the old one — followed by the ``/31``: both ``IpamIPAddress`` ends
        and the prefix that contained them, which returns it to the pool. Leaving the prefix would leak
        one per move, since the next allocation keys on a new ``identifier`` (the port-id pair, which
        the new port changes).
        """
        old_leaf_port = await self._client.get(
            kind=NetworkInterface, id=old_leaf_port.id, include=["ip_address", "link", "device"]
        )
        server_side = await self._client.get(kind=ServerInterface, id=server_port_id, include=["ip_address", "link"])
        link_id = old_leaf_port.link.id
        leaf_id = old_leaf_port.device.id
        address_ids = [side.ip_address.id for side in (old_leaf_port, server_side) if side.ip_address.id is not None]

        old_leaf_port.ip_address = None  # type: ignore[assignment]
        old_leaf_port.link = None  # type: ignore[assignment]
        old_leaf_port.status.value = "inactive"
        await old_leaf_port.save(allow_upsert=True, update_group_context=False)

        if link_id is not None:
            link = await self._client.get(kind=NetworkLink, id=link_id)
            await link.delete()
            self._logger.info(f"Released cable {link.name.value}")

        await self._release_p2p_prefix(address_ids)
        return leaf_id

    async def _release_p2p_prefix(self, address_ids: list[str]) -> None:
        """Delete the superseded ``/31``'s addresses and the prefix holding them (L2: nothing to do)."""
        if not address_ids:
            return

        prefix_ids = set()
        for address_id in address_ids:
            address = await self._client.get(kind=IpamIPAddress, id=address_id, include=["ip_prefix"])
            if address.ip_prefix.id is not None:
                prefix_ids.add(address.ip_prefix.id)
            await address.delete()

        # The prefix only frees up once it holds no addresses, hence after the loop above.
        for prefix_id in sorted(prefix_ids):
            prefix = await self._client.get(kind=IpamIPPrefix, id=prefix_id)
            await prefix.delete()
            self._logger.info(f"Released prefix {prefix.prefix.value} back to the pool")

    async def _delete_ebgp_pair(self, leaf_id: str, server_id: str) -> None:
        """Delete both directions of the leaf<->server eBGP session left behind by a move to another leaf."""
        stale = await self._client.filters(
            kind=NetworkBGPSession, device__ids=[leaf_id, server_id], peer_device__ids=[leaf_id, server_id]
        )
        for session in stale:
            await session.delete()
            self._logger.info(f"Deleted stale eBGP session {session.name.value}")
