from __future__ import annotations

import hashlib
import logging
from typing import NamedTuple

from infrahub_sdk.generator import InfrahubGenerator
from infrahub_sdk.protocols import CoreIPPrefixPool, CoreNumberPool

from infrahub_solution_ai_dc.addressing import assign_ip_addresses_to_p2p_connections
from infrahub_solution_ai_dc.generator import GeneratorMixin
from infrahub_solution_ai_dc.protocols import (
    IpamIPAddress,
    IpamIPPrefix,
    LocationRack,
    NetworkBGPSession,
    NetworkDevice,
    NetworkFabric,
    NetworkInterface,
    NetworkLink,
    NetworkPod,
    NetworkSegment,
    NetworkServer,
    NetworkServerService,
    ServerInterface,
)
from infrahub_solution_ai_dc.servers import (
    peer_endpoint_id,
    placement_matches_request,
    port_is_free,
    require_allocated,
    select_free_server_port,
    select_least_utilized_rack,
    upsert_ebgp_session,
    validate_explicit_port,
    validate_service,
)

from .generate_server_query import (
    ServerGeneratorQuery,
    ServerGeneratorQueryServiceNode,
    _LeafInterfaceNode,
    _RackNode,
)

SERVER_ASN_POOL = "Server ASN Pool"
SERVER_PORT_NAME = "eth1"  # deterministic name of the server's own leaf-facing port
SERVER_P2P_PREFIX_LEN = 31
SERVER_P2P_PREFIX_ROLE = "server_p2p"


def server_hostname(service_name: str) -> str:
    """The deterministic hostname a service's ``NetworkServer`` carries — the generator's upsert key."""
    return f"server-{service_name}"


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


class ServerGenerator(InfrahubGenerator, GeneratorMixin):
    """Materialize a ``NetworkServerService`` by attaching a server to a fabric leaf.

    Resolves the request's scope through ``vrf.tenant.fabric``, picks a placement (least-utilized rack +
    lowest free ``role:server`` leaf port), creates the ``NetworkServer`` and its single port, cables it to
    the leaf with a ``NetworkLink``, and — for an L3 service — allocates the server ASN (global pool) and a
    ``server_p2p`` /31 from the pod's ``server_prefix_pool`` and upserts the paired eBGP sessions.

    All operator/service-node writes use ``update_group_context=False`` (mirroring ``OverlayGenerator``) so
    the generator group's cleanup never prunes them. An unchanged run is idempotent, and **placement reuse
    is what makes that true**: every other upsert key is derived from the placement, so a re-run that
    reused it re-derives the same server hostname, the same ``(server, name)`` ``human_friendly_id`` for
    the port, the same ``NetworkLink`` name, the same ``/31`` allocation identifier and the same
    ``"{a}__{b}"`` session names — while the ASN is allocated only when unset. Re-running yields an empty
    diff. A re-run that *re-selected* placement instead could not: see :meth:`existing_placement`.

    Note that a re-run is the norm, not an edge case — stamping the checksum at the end of a first run
    fires ``trigger-server-generator-update-checksum`` (``triggers.yml``), so every service is processed
    at least twice.

    ``rack`` and ``leaf_interface`` are **round-trip** fields, not inputs the generator only reads: it
    honors whichever the operator set and writes back whichever it resolved (:meth:`record_placement`),
    so a service always ends up naming the placement that exists in the graph. That write-back is what
    makes :meth:`existing_placement` running *before* explicit resolution load-bearing rather than a
    mere optimization — the written-back port is by then cabled, so the explicit path's "must be free"
    check would reject every single re-run.

    Because those fields round-trip, editing one is how a server is moved, and the generator is
    therefore **not** purely additive: :meth:`release_placement` deletes the superseded cable, /31 and
    (when the leaf changed) eBGP sessions. Deletion is confined to that one call and only ever runs on
    a placement this service itself owns — never on a port cabled to another server
    (:meth:`port_is_reclaimable`).

    The L2 and L3 branches in :meth:`generate` share the same placement + server + cabling foundation; the
    L3 branch (:meth:`configure_l3`) additionally allocates the ASN and /31 and upserts the eBGP pair, while the
    L2 branch (:meth:`attach_segment_rack`) instead adds the chosen rack to the segment's placement and creates
    no BGP/IP. :meth:`servers.validate_service` fail-loud-rejects contradictory requests before any write.

    Placement (:meth:`resolve_placement`) reuses what a previous run already cabled
    (:meth:`existing_placement`); for an unplaced service it is automatic by default (least-utilized rack +
    lowest free ``role:server`` port) and honors an explicit ``rack``/``leaf_interface`` exactly when the
    service names one (:meth:`resolve_explicit_placement`), failing loud on any invalid explicit placement
    (US3/FR-004).
    """

    logger = logging.getLogger("infrahub.tasks")

    async def generate(self, data: dict) -> None:
        parsed = ServerGeneratorQuery(**data)
        assert parsed.network_server_service.edges
        service = parsed.network_server_service.edges[0].node
        assert service is not None
        assert service.name is not None
        assert service.name.value is not None
        assert service.vrf is not None
        assert service.vrf.node is not None
        assert service.vrf.node.tenant is not None
        assert service.vrf.node.tenant.node is not None
        assert service.vrf.node.tenant.node.fabric is not None
        assert service.vrf.node.tenant.node.fabric.node is not None

        service_name = service.name.value
        layer = service.layer.value if service.layer and service.layer.value else "l3"
        fabric_id = service.vrf.node.tenant.node.fabric.node.id
        service_vrf_id = service.vrf.node.id

        # Resolve the (optional) segment + its VRF from the parsed query.
        segment = service.segment.node if service.segment else None
        segment_id = segment.id if segment else None
        segment_vrf_id = segment.vrf.node.id if segment and segment.vrf and segment.vrf.node else None

        # Fail-loud validation BEFORE any object is created (no partial objects): L2 requires a
        # segment in the service's VRF; L3 forbids a segment (contradictory request).
        validate_service(layer, service_name, service_vrf_id, segment_id, segment_vrf_id)

        # Placement: least-utilized rack + lowest free role:server leaf port (fail-loud on none).
        placement = await self.resolve_placement(service, fabric_id)

        # Shared across L2/L3: create the server, its port, and the server<->leaf link.
        server = await self.materialize_server(service_name, layer, placement.rack.id)
        server_port = await self.materialize_server_port(server)

        # Free what the new placement supersedes *before* cabling: the server's own port holds a
        # cardinality-1 link, so a stale cable would make the new one unrepresentable.
        await self.release_placement(placement, server, server_port)

        await self.cable_server_to_leaf(server, server_port, placement.leaf, placement.leaf_port)

        if layer == "l3":
            await self.configure_l3(server, server_port, placement.leaf, placement.leaf_port, fabric_id)
        else:
            # L2: attach the chosen leaf's rack to the segment's placement. No ASN, no /31, no session —
            # overlay materialization onto the leaf remains the OverlayGenerator's separate step (SD8).
            assert segment_id is not None  # guaranteed by validate_service for the L2 layer
            await self.attach_segment_rack(segment_id, placement.rack)

        await self.record_placement(service.id, server.id, placement.rack.id, placement.leaf_port.id)
        await self.update_checksum(service.id, [server.id, server_port.id, placement.leaf_port.id])

    async def resolve_placement(self, service: ServerGeneratorQueryServiceNode, fabric_id: str) -> ResolvedPlacement:
        """Resolve where the server goes — reused, re-placed, automatic, or explicit (US3/T036).

        **Reused** (the service's server is already cabled and ``rack``/``leaf_interface`` still name
        that placement): return it unchanged via :meth:`existing_placement`. This is the idempotent
        path and, because those fields are written back, the path every re-run takes — see that method
        for why recomputing instead is not merely wasteful but guaranteed to fail.

        **Re-placed** (already cabled, but the operator re-pointed ``rack`` or ``leaf_interface``):
        resolve the new placement explicitly and report the old leaf port as ``released_port`` so
        :meth:`generate` tears the superseded cable down before laying the new one. Which field the
        operator actually moved decides what is honored: a changed port names its own rack, so a
        ``rack`` still holding the *written-back* previous value must not veto the move (and vice
        versa). Only a change to both is required to be self-consistent.

        Automatic (unplaced, and neither ``rack`` nor ``leaf_interface`` on the service): pick the
        least-utilized eligible rack in the fabric, then the lowest free ``role:server`` port among
        that rack's leaves.

        Explicit (unplaced, either provided): honor the request exactly via
        :meth:`resolve_explicit_placement`, failing loud on any invalid placement. All validation
        happens **before** any object is created, so a rejected request leaves no partial objects
        (FR-004/SC-002).
        """
        explicit_rack = service.rack.node if service.rack and service.rack.node else None
        explicit_port = service.leaf_interface.node if service.leaf_interface and service.leaf_interface.node else None
        hostname = server_hostname(str(service.name.value)) if service.name else ""

        existing = await self.existing_placement(service)
        if existing is not None:
            rack, leaf, leaf_port = existing
            if placement_matches_request(
                placed_rack_id=rack.id,
                placed_port_id=leaf_port.id,
                requested_rack_id=explicit_rack.id if explicit_rack is not None else None,
                requested_port_id=explicit_port.id if explicit_port is not None else None,
            ):
                self.logger.info(
                    f"Reusing placement: rack {rack.name.value}, leaf {leaf.hostname.value}, "
                    f"port {leaf_port.name.value}"
                )
                return ResolvedPlacement(rack, leaf, leaf_port)

            # Re-placement: honor only the side the operator moved, so the other side's written-back
            # value (which still describes the placement being left behind) cannot contradict it.
            port_moved = explicit_port is not None and explicit_port.id != leaf_port.id
            rack_moved = explicit_rack is not None and explicit_rack.id != rack.id
            requested_rack = explicit_rack if rack_moved else None
            requested_port = explicit_port if port_moved else None

            new_rack, new_leaf, new_port = await self.resolve_explicit_placement(
                requested_rack, requested_port, fabric_id, hostname
            )
            self.logger.info(
                f"Re-placing from rack {rack.name.value} port {leaf_port.name.value} to "
                f"rack {new_rack.name.value} leaf {new_leaf.hostname.value} port {new_port.name.value}"
            )
            # The port being left, plus the target if it too was already dirty.
            released = (leaf_port, *(() if port_is_free(new_port) else (new_port,)))
            return ResolvedPlacement(new_rack, new_leaf, new_port, released_ports=released)

        if explicit_rack is None and explicit_port is None:
            rack = await self.select_rack(fabric_id)
            leaf, leaf_port = await self.select_leaf_port(rack)
            released = ()
        else:
            rack, leaf, leaf_port = await self.resolve_explicit_placement(
                explicit_rack, explicit_port, fabric_id, hostname
            )
            # An explicit port carrying this service's own leftovers (a manually deleted server) is
            # honored, but its stale cable/IP has to go before it can be re-used.
            released = () if port_is_free(leaf_port) else (leaf_port,)

        self.logger.info(f"Placement: rack {rack.name.value}, leaf {leaf.hostname.value}, port {leaf_port.name.value}")
        return ResolvedPlacement(rack, leaf, leaf_port, released_ports=released)

    async def placed_server_id(self, service: ServerGeneratorQueryServiceNode) -> str | None:
        """Return the id of this service's already-materialized server, or ``None`` if there is none.

        Prefers the ``service.server`` relationship and falls back to the deterministic hostname, so a
        server cabled by a run that never reached :meth:`record_placement` is still recognized.
        """
        server = service.server.node if service.server else None
        if server is not None and server.id is not None:
            return server.id

        service_name = service.name.value if service.name else None
        if service_name is None:
            return None
        servers = await self.client.filters(kind=NetworkServer, hostname__value=server_hostname(service_name))
        return servers[0].id if servers else None

    async def existing_placement(
        self, service: ServerGeneratorQueryServiceNode
    ) -> tuple[LocationRack, NetworkDevice, NetworkInterface] | None:
        """Recover the placement a previous run materialized, or ``None`` when the service is unplaced.

        Placement **must not** be recomputed for a service that already has a cabled server, and not
        just to save work: :func:`servers.select_free_server_port` counts a port with a link as *not*
        free, so a re-run necessarily picks a *different* port. That yields a differently-named
        ``NetworkLink`` on the server's single ``eth1``, whose ``networkendpoint__networklink``
        cardinality is 1 — so the second link is rejected and the run dies *after*
        :meth:`materialize_server` has already re-pointed ``server.rack``. Reusing the placement is
        what makes the whole chain (server, port, link, /31, sessions) idempotent: every downstream
        upsert key is derived from it, including the ``/31`` allocation identifier (the port-id pair).

        Since :meth:`record_placement` writes the resolved placement back onto the service, this lookup
        is also what stops a re-run from re-entering the *explicit* path with the values it wrote there
        — where the now-cabled port would fail the "must be free" check on every run.

        The server is found through ``service.server`` when set, and otherwise by the deterministic
        hostname :meth:`materialize_server` assigns. That fallback matters: :meth:`generate` cables at
        step 4 but only points ``service.server`` at step 7, so a failure in between (an exhausted ASN
        pool, an unallocated ``overlay_asn``) leaves a cabled server the service does not reference —
        and keying reuse solely on the relationship would re-select a port and crash exactly as before.

        From there it walks server -> its ``eth1`` -> that port's link -> the link's far endpoint (the
        leaf port) -> its leaf -> its rack. Returns ``None`` at any missing step so a half-built server
        (created but never cabled) falls through to normal selection and gets finished rather than being
        reused in a broken state.
        """
        server_id = await self.placed_server_id(service)
        if server_id is None:
            return None

        server_ports = await self.client.filters(
            kind=ServerInterface,
            server__ids=[server_id],
            name__value=SERVER_PORT_NAME,
            include=["link"],
        )
        server_port = next((port for port in server_ports if port.link.id is not None), None)
        if server_port is None:
            return None

        link = await self.client.get(kind=NetworkLink, id=server_port.link.id, include=["endpoints"])
        leaf_port_id = peer_endpoint_id(
            [peer.id for peer in link.endpoints.peers if peer.id is not None], server_port.id
        )
        if leaf_port_id is None:
            return None

        leaf_port = await self.client.get(
            kind=NetworkInterface, id=leaf_port_id, include=["ip_address", "link", "device"]
        )
        if leaf_port.device.id is None:
            return None
        leaf = await self.client.get(kind=NetworkDevice, id=leaf_port.device.id, include=["rack"])
        if leaf.rack.id is None:
            return None
        rack = await self.client.get(kind=LocationRack, id=leaf.rack.id)
        return rack, leaf, leaf_port

    async def resolve_explicit_placement(
        self,
        explicit_rack: _RackNode | None,
        explicit_port: _LeafInterfaceNode | None,
        fabric_id: str,
        hostname: str,
    ) -> tuple[LocationRack, NetworkDevice, NetworkInterface]:
        """Honor an explicit ``rack``/``leaf_interface`` exactly, or fail loud (US3, FR-004/SC-002).

        Validation order (all reads, all before any write — a rejection leaves no partial objects):

        * an explicit rack must belong to the service's fabric;
        * a rack given without a port falls back to the lowest free ``role:server`` port on it;
        * an explicit port is re-fetched (the generator query omits ``ip_address``/``link``), its leaf
          resolved, and the chosen rack taken as the explicit rack or the port's leaf's rack;
        * the port must sit on a leaf of the chosen rack, and be ``role:server`` + free
          (:func:`validate_explicit_port`) — unless it is occupied by this service's own leftovers
          (:meth:`port_is_reclaimable`), which the caller releases instead of refusing.

        ``hostname`` is the service's deterministic server hostname, used only for that ownership test.

        Last-free-port contention is **not** currently hard-enforced. Two services racing for the same
        port both pass this read-time check, and nothing on the write side stops the second racer:
        ``NetworkLink.endpoints`` carries no uniqueness constraint, and each server's link has a distinct
        name, so the loser's ``save`` silently re-points ``leaf_port.link`` instead of failing loud.
        Strict enforcement — a uniqueness constraint on the endpoint relationship, validated against a
        running stack — is a deferred follow-up (it needs the stack to verify) and is not attempted here.
        """
        fabric_rack_ids = await self._fabric_rack_ids(fabric_id)

        if explicit_rack is not None and explicit_rack.id not in fabric_rack_ids:
            msg = (
                f"Cannot honor explicit rack {explicit_rack.id!r}: it is not a rack of the "
                f"service's fabric {fabric_id!r}"
            )
            raise ValueError(msg)

        if explicit_port is None:
            # Rack given without a port: honor the rack, auto-pick its lowest free role:server port.
            assert explicit_rack is not None
            rack = await self.client.get(kind=LocationRack, id=explicit_rack.id)
            leaf, leaf_port = await self.select_leaf_port(rack)
            return rack, leaf, leaf_port

        # A port is named: re-fetch it fully (the query omits ip_address/link) and resolve its leaf.
        leaf_port = await self.client.get(
            kind=NetworkInterface, id=explicit_port.id, include=["ip_address", "link", "device"]
        )
        leaf_id = leaf_port.device.id
        if leaf_id is None:
            msg = (
                f"Cannot honor explicit leaf_interface {explicit_port.id!r}: it is not on any device (not a leaf port)"
            )
            raise ValueError(msg)
        leaf = await self.client.get(kind=NetworkDevice, id=leaf_id, include=["rack"])

        # Resolve the chosen rack: the explicit one (validated above) or the port's leaf's rack.
        rack_id = explicit_rack.id if explicit_rack is not None else leaf.rack.id
        if rack_id is None:
            msg = f"Cannot honor explicit leaf_interface {explicit_port.id!r}: its leaf {leaf_id!r} is in no rack"
            raise ValueError(msg)
        if explicit_rack is None and rack_id not in fabric_rack_ids:
            msg = (
                f"Cannot honor explicit leaf_interface {explicit_port.id!r}: its leaf's rack {rack_id!r} "
                f"is not in the service's fabric {fabric_id!r}"
            )
            raise ValueError(msg)
        rack = await self.client.get(kind=LocationRack, id=rack_id)

        # The port must sit on a leaf of the chosen rack (trivially true when the rack was derived).
        if leaf.rack.id != rack.id:
            msg = (
                f"Cannot honor explicit leaf_interface {leaf_port.name.value!r}: its leaf "
                f"{leaf.hostname.value!r} is not on rack {rack.name.value!r}"
            )
            raise ValueError(msg)

        # role:server + free (pure, unit-tested) — waiving "free" only for our own leftovers.
        reclaimable = not port_is_free(leaf_port) and await self.port_is_reclaimable(leaf_port, hostname)
        validate_explicit_port(leaf_port, rack.name.value, reclaimable=reclaimable)
        return rack, leaf, leaf_port

    async def port_is_reclaimable(self, leaf_port: NetworkInterface, hostname: str) -> bool:
        """Return True when an occupied leaf port holds only *this* service's leftovers, safe to tear down.

        Deciding this is what keeps :meth:`release_leaf_port`'s deletions safe: an explicitly requested
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

        link = await self.client.get(kind=NetworkLink, id=leaf_port.link.id, include=["endpoints"])
        far_ends = [peer.id for peer in link.endpoints.peers if peer.id is not None and peer.id != leaf_port.id]
        if not far_ends:
            return True
        if len(far_ends) > 1:
            return False

        # ``filters`` (not ``get``) so a far end of another kind — or one already deleted — is an empty
        # result rather than a raise.
        server_ports = await self.client.filters(kind=ServerInterface, ids=far_ends, include=["server"])
        if not server_ports:
            fabric_ports = await self.client.filters(kind=NetworkInterface, ids=far_ends)
            return not fabric_ports  # nothing resolves at all => a dead cable; a fabric port => not ours
        owner_id = server_ports[0].server.id
        if owner_id is None:
            return True
        owner = await self.client.get(kind=NetworkServer, id=owner_id)
        return bool(owner.hostname.value == hostname)

    async def _fabric_rack_ids(self, fabric_id: str) -> set[str]:
        """Return the set of ``LocationRack`` ids belonging to the fabric (via its pods)."""
        pods = await self.client.filters(kind=NetworkPod, parent__ids=[fabric_id])
        pod_ids = [pod.id for pod in pods]
        racks = await self.client.filters(kind=LocationRack, pod__ids=pod_ids) if pod_ids else []
        return {rack.id for rack in racks}

    async def select_rack(self, fabric_id: str) -> LocationRack:
        """Return the least-utilized rack in the fabric (fewest attached servers), fail-loud if none."""
        pods = await self.client.filters(kind=NetworkPod, parent__ids=[fabric_id])
        pod_ids = [pod.id for pod in pods]
        racks = await self.client.filters(kind=LocationRack, pod__ids=pod_ids) if pod_ids else []

        # Count servers only within this fabric's racks (O(fabric), not instance-wide); servers on
        # racks outside the fabric were discarded anyway, so scoping the query is behavior-preserving.
        fabric_rack_ids = [rack.id for rack in racks]
        servers = (
            await self.client.filters(kind=NetworkServer, rack__ids=fabric_rack_ids, include=["rack"])
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

    async def select_leaf_port(self, rack: LocationRack) -> tuple[NetworkDevice, NetworkInterface]:
        """Return the lowest free ``role:server`` port on a leaf of ``rack`` (fail-loud if none free)."""
        leaves = await self.client.filters(kind=NetworkDevice, role__value="leaf", rack__ids=[rack.id])
        if not leaves:
            msg = f"Cannot place server service: rack {rack.name.value} has no leaf switch"
            raise ValueError(msg)

        leaves_by_id = {leaf.id: leaf for leaf in leaves}
        server_ports = await self.client.filters(
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

    async def materialize_server(self, service_name: str, layer: str, rack_id: str) -> NetworkServer:
        """Create/upsert the ``NetworkServer`` (deterministic hostname), never joining any device group."""
        server = await self.client.create(
            kind=NetworkServer,
            hostname=server_hostname(service_name),
            layer=layer,
            rack={"id": rack_id},
        )
        await server.save(allow_upsert=True, update_group_context=False)
        # Re-fetch so subsequent relationship/pool writes read a fully-resolved node.
        return await self.client.get(kind=NetworkServer, id=server.id)

    async def materialize_server_port(self, server: NetworkServer) -> ServerInterface:
        """Create/upsert the server's own ``ServerInterface`` on its ``(server, name)`` identity."""
        port = await self.client.create(
            kind=ServerInterface,
            name=SERVER_PORT_NAME,
            role="production",
            status="active",
            server={"id": server.id},
        )
        await port.save(allow_upsert=True, update_group_context=False)
        return await self.client.get(kind=ServerInterface, id=port.id, include=["ip_address", "link"])

    async def cable_server_to_leaf(
        self,
        server: NetworkServer,
        server_port: ServerInterface,
        leaf: NetworkDevice,
        leaf_port: NetworkInterface,
    ) -> None:
        """Create/upsert the ``NetworkLink`` between the leaf port and the server port.

        Built by hand rather than via ``cabling.connect_interface_maps`` because that helper derives the link
        name from ``interface.device.display_label`` — a ``ServerInterface`` is owned by a server, not a device.
        """
        name = f"{leaf.hostname.value}-{leaf_port.name.value}__{server.hostname.value}-{server_port.name.value}"
        link = await self.client.create(
            kind="NetworkLink",
            name=name,
            medium="copper",
            endpoints=[leaf_port, server_port],
        )
        await link.save(allow_upsert=True, update_group_context=False)

        # Both ends go active. Written out per kind rather than looped: the two ends are distinct kinds
        # and their common ancestor (NetworkEndpoint) carries no ``status``.
        leaf_end = await self.client.get(kind=NetworkInterface, id=leaf_port.id, include=["link"])
        leaf_end.status.value = "active"
        await leaf_end.save(allow_upsert=True, update_group_context=False)

        server_end = await self.client.get(kind=ServerInterface, id=server_port.id, include=["link"])
        server_end.status.value = "active"
        await server_end.save(allow_upsert=True, update_group_context=False)
        self.logger.info(f"Cabled {name}")

    async def release_placement(
        self, placement: ResolvedPlacement, server: NetworkServer, server_port: ServerInterface
    ) -> None:
        """Clear everything ``placement`` supersedes, so the server can be cabled to its new port.

        The generator's only destructive step, and a no-op unless :meth:`resolve_placement` reported a
        released port — the operator moved the service, or the target port still carries this service's
        own leftovers. :meth:`port_is_reclaimable` has already established that nothing being removed
        belongs to another server.

        Each released port is emptied by :meth:`release_leaf_port`. The eBGP session pair is handled
        here instead, because it belongs to the *leaf* rather than the port: sessions are keyed by
        ``"{device}__{peer}"`` on ``(device, peer_device)``, so a move between ports of one leaf leaves
        them correct and :func:`upsert_ebgp_session` merely refreshes them, while a move to another leaf
        would otherwise strand the old pair, still rendering on the leaf the server just left. The
        rendered neighbor address needs no fixup either way — the template reads it from the peer's
        interface at render time rather than from the session.
        """
        stale_leaf_ids: set[str] = set()
        for released in placement.released_ports:
            leaf_id = await self.release_leaf_port(released, server_port)
            if leaf_id is not None and leaf_id != placement.leaf.id:
                stale_leaf_ids.add(leaf_id)

        for leaf_id in sorted(stale_leaf_ids):
            await self.delete_ebgp_pair(leaf_id, server.id)

    async def release_leaf_port(self, old_leaf_port: NetworkInterface, server_port: ServerInterface) -> str | None:
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
        old_leaf_port = await self.client.get(
            kind=NetworkInterface, id=old_leaf_port.id, include=["ip_address", "link", "device"]
        )
        server_side = await self.client.get(kind=ServerInterface, id=server_port.id, include=["ip_address", "link"])
        link_id = old_leaf_port.link.id
        leaf_id = old_leaf_port.device.id
        address_ids = [side.ip_address.id for side in (old_leaf_port, server_side) if side.ip_address.id is not None]

        old_leaf_port.ip_address = None  # type: ignore[assignment]
        old_leaf_port.link = None  # type: ignore[assignment]
        old_leaf_port.status.value = "inactive"
        await old_leaf_port.save(allow_upsert=True, update_group_context=False)

        if link_id is not None:
            link = await self.client.get(kind=NetworkLink, id=link_id)
            await link.delete()
            self.logger.info(f"Released cable {link.name.value}")

        await self.release_p2p_prefix(address_ids)
        return leaf_id

    async def release_p2p_prefix(self, address_ids: list[str]) -> None:
        """Delete the superseded ``/31``'s addresses and the prefix holding them (L2: nothing to do)."""
        if not address_ids:
            return

        prefix_ids = set()
        for address_id in address_ids:
            address = await self.client.get(kind=IpamIPAddress, id=address_id, include=["ip_prefix"])
            if address.ip_prefix.id is not None:
                prefix_ids.add(address.ip_prefix.id)
            await address.delete()

        # The prefix only frees up once it holds no addresses, hence after the loop above.
        for prefix_id in sorted(prefix_ids):
            prefix = await self.client.get(kind=IpamIPPrefix, id=prefix_id)
            await prefix.delete()
            self.logger.info(f"Released prefix {prefix.prefix.value} back to the pool")

    async def delete_ebgp_pair(self, leaf_id: str, server_id: str) -> None:
        """Delete both directions of the leaf<->server eBGP session left behind by a move to another leaf."""
        stale = await self.client.filters(
            kind=NetworkBGPSession, device__ids=[leaf_id, server_id], peer_device__ids=[leaf_id, server_id]
        )
        for session in stale:
            await session.delete()
            self.logger.info(f"Deleted stale eBGP session {session.name.value}")

    async def attach_segment_rack(self, segment_id: str, rack: LocationRack) -> None:
        """Idempotently add the chosen leaf's rack to the L2 segment's ``racks`` placement.

        Edge-scoped ``add_relationships`` (the pattern from ``OverlayGenerator.materialize_segments`` /
        ``generate_tenant``): only the single ``(segment, rack)`` edge is touched, so a re-run where the
        edge already exists is a no-op and other racks on the segment are never rewritten. No BGP session,
        /31, or ASN is created on the L2 path — carrying the segment onto the rack's leaves is the
        OverlayGenerator's separate step (research SD8).
        """
        segment = await self.client.get(kind=NetworkSegment, id=segment_id, include=["racks"])
        current = {peer.id for peer in segment.racks.peers if peer.id is not None}
        if rack.id not in current:
            await segment.add_relationships("racks", [rack.id])
            self.logger.info(f"Added rack {rack.name.value} to segment {segment.name.value} placement")

    async def configure_l3(
        self,
        server: NetworkServer,
        server_port: ServerInterface,
        leaf: NetworkDevice,
        leaf_port: NetworkInterface,
        fabric_id: str,
    ) -> None:
        """Allocate the server ASN + /31, then upsert the paired eBGP sessions (leaf<->server)."""
        server_asn = await self.allocate_server_asn(server.id)
        overlay_asn = await self.resolve_overlay_asn(fabric_id)

        pool = await self.server_prefix_pool(leaf.id)
        await assign_ip_addresses_to_p2p_connections(
            client=self.client,
            logger=self.logger,
            connections=[(leaf_port, server_port)],
            prefix_len=SERVER_P2P_PREFIX_LEN,
            prefix_role=SERVER_P2P_PREFIX_ROLE,
            pool=pool,
            # The leaf port belongs to the rack generator. Group-tracking it here would make the
            # cleanup of a run that moved the server off it delete the port outright.
            update_group_context=False,
        )

        # eBGP pair: the leaf peers the server's ASN; the server peers the fabric overlay ASN.
        leaf = await self.client.get(kind=NetworkDevice, id=leaf.id)
        server = await self.client.get(kind=NetworkServer, id=server.id)
        await upsert_ebgp_session(
            self.client, self.logger, device=leaf, peer=server, local_as=overlay_asn, remote_as=server_asn
        )
        await upsert_ebgp_session(
            self.client, self.logger, device=server, peer=leaf, local_as=server_asn, remote_as=overlay_asn
        )

    async def allocate_server_asn(self, server_id: str) -> int:
        """Allocate the server ASN from the global pool, only if unset; re-fetch to read the value."""
        server = await self.client.get(kind=NetworkServer, id=server_id)
        if server.asn.value is None:
            server.asn.value = await self.client.get(kind=CoreNumberPool, name__value=SERVER_ASN_POOL)  # type: ignore[assignment]
            await server.save(allow_upsert=True, update_group_context=False)
            # Pool-allocated values are not readable on the returned node; re-fetch to read them.
            server = await self.client.get(kind=NetworkServer, id=server_id)
        return require_allocated(server.asn.value, SERVER_ASN_POOL)

    async def resolve_overlay_asn(self, fabric_id: str) -> int:
        """Return the fabric's overlay ASN (the leaf's local AS / the server's remote AS), fail-loud if not yet allocated."""
        fabric = await self.client.get(kind=NetworkFabric, id=fabric_id)
        overlay_asn = fabric.overlay_asn.value
        if overlay_asn is None:
            msg = f"Fabric {fabric_id} has no overlay_asn allocated yet; cannot pair server eBGP session"
            raise ValueError(msg)
        return overlay_asn

    async def server_prefix_pool(self, leaf_id: str) -> CoreIPPrefixPool:
        """Resolve the leaf pod's ``server_prefix_pool`` (fail-loud if the pod never carved one)."""
        leaf = await self.client.get(kind=NetworkDevice, id=leaf_id, include=["pod"])
        pod = await self.client.get(kind=NetworkPod, id=leaf.pod.id, include=["server_prefix_pool"])
        if pod.server_prefix_pool.id is None:
            msg = f"Pod {pod.name.value} has no server_prefix_pool; run the pod generator first"
            raise ValueError(msg)
        return await self.client.get(kind=CoreIPPrefixPool, id=pod.server_prefix_pool.id)

    async def record_placement(self, service_id: str, server_id: str, rack_id: str, leaf_port_id: str) -> None:
        """Write back what the run materialized: the server, and the placement it resolved.

        ``rack``/``leaf_interface`` round-trip rather than being read-only inputs, so an
        automatically-placed service ends up naming its rack and leaf port instead of staying blank,
        and an operator reads the real placement off the service itself. Writing them also makes them
        the handle for moving the server later — editing one re-places it (:meth:`resolve_placement`).

        All three are compared before assigning and share a single ``save``, so the re-run that the
        checksum stamp always triggers writes nothing at all.
        """
        service = await self.client.get(kind=NetworkServerService, id=service_id)
        updates = {"server": server_id, "rack": rack_id, "leaf_interface": leaf_port_id}
        changed = [field for field, value in updates.items() if getattr(service, field).id != value]
        if not changed:
            return

        for field in changed:
            setattr(service, field, {"id": updates[field]})
        await service.save(allow_upsert=True, update_group_context=False)
        self.logger.info(f"Recorded {', '.join(changed)} on the service")

    async def update_checksum(self, service_id: str, object_ids: list[str]) -> None:
        """Stamp a content checksum (over the materialized object ids) on the service.

        Stamped with ``update_group_context=False`` and only when it changes, so an unchanged re-run is a
        no-op (no self-retrigger loop), mirroring ``OverlayGenerator.update_checksum``.
        """
        payload = ",".join(sorted(object_ids))
        checksum = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        service = await self.client.get(kind=NetworkServerService, id=service_id)
        if service.checksum.value != checksum:
            service.checksum.value = checksum
            await service.save(allow_upsert=True, update_group_context=False)
