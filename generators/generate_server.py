from __future__ import annotations

import logging

from infrahub_sdk.generator import InfrahubGenerator
from infrahub_sdk.protocols import CoreIPPrefixPool, CoreNumberPool

from infrahub_solution_ai_dc.addressing import assign_ip_addresses_to_p2p_connections
from infrahub_solution_ai_dc.checksum import Checksum
from infrahub_solution_ai_dc.placement import (
    SERVER_PORT_NAME,
    PlacementRequest,
    ServerPlacement,
    server_hostname,
)
from infrahub_solution_ai_dc.protocols import (
    LocationRack,
    NetworkDevice,
    NetworkFabric,
    NetworkInterface,
    NetworkPod,
    NetworkSegment,
    NetworkServer,
    NetworkServerService,
    ServerInterface,
)
from infrahub_solution_ai_dc.query import only_node, related, related_id, value_of
from infrahub_solution_ai_dc.servers import require_allocated, upsert_ebgp_session, validate_service

from .generate_server_query import ServerGeneratorQuery, ServerGeneratorQueryServiceNode

SERVER_ASN_POOL = "Server ASN Pool"
SERVER_P2P_PREFIX_LEN = 31
SERVER_P2P_PREFIX_ROLE = "server_p2p"


class ServerGenerator(InfrahubGenerator):
    """Materialize a ``NetworkServerService`` by attaching a server to a fabric leaf.

    Resolves the request's scope through ``vrf.tenant.fabric``, asks
    :class:`~infrahub_solution_ai_dc.placement.ServerPlacement` where the server goes, creates the
    ``NetworkServer`` and its single port, cables it to the leaf with a ``NetworkLink``, and — for an
    L3 service — allocates the server ASN (global pool) and a ``server_p2p`` /31 from the pod's
    ``server_prefix_pool`` and upserts the paired eBGP sessions.

    All operator/service-node writes use ``update_group_context=False`` (mirroring ``OverlayGenerator``)
    so the generator group's cleanup never prunes them. An unchanged run is idempotent, and **placement
    reuse is what makes that true**: every other upsert key is derived from the placement, so a re-run
    that reused it re-derives the same server hostname, the same ``(server, name)``
    ``human_friendly_id`` for the port, the same ``NetworkLink`` name, the same ``/31`` allocation
    identifier and the same ``"{a}__{b}"`` session names — while the ASN is allocated only when unset.
    Re-running yields an empty diff.

    Note that a re-run is the norm, not an edge case — stamping the checksum at the end of a first run
    fires ``trigger-server-generator-update-checksum`` (``triggers.yml``), so every service is processed
    at least twice.

    ``rack`` and ``leaf_interface`` are **round-trip** fields, not inputs the generator only reads: it
    hands whichever the operator set to placement and writes back whichever came out
    (:meth:`record_placement`), so a service always ends up naming the placement that exists in the
    graph. Editing one is therefore how a server is moved, which makes this generator **not** purely
    additive — but every deletion a move implies is confined to
    :meth:`~infrahub_solution_ai_dc.placement.ServerPlacement.release`, which never touches a placement
    this service does not own.

    The L2 and L3 branches in :meth:`generate` share the same placement + server + cabling foundation;
    the L3 branch (:meth:`configure_l3`) additionally allocates the ASN and /31 and upserts the eBGP
    pair, while the L2 branch (:meth:`attach_segment_rack`) instead adds the chosen rack to the
    segment's placement and creates no BGP/IP. :func:`~infrahub_solution_ai_dc.servers.validate_service`
    fail-loud-rejects contradictory requests before any write.
    """

    logger = logging.getLogger("infrahub.tasks")

    @property
    def placement(self) -> ServerPlacement:
        """Where the server goes, and what a move leaves behind."""
        return ServerPlacement(self.client, self.logger)

    @staticmethod
    def placement_request(service: ServerGeneratorQueryServiceNode, fabric_id: str) -> PlacementRequest:
        """Read the four values placement decides on out of the parsed service node.

        ``rack`` and ``leaf_interface`` are passed through exactly as found: placement compares them
        against what is cabled and cannot, from the values alone, tell an operator's request from the
        one a previous run wrote back — nor does it need to.
        """
        server = service.server.node if service.server else None
        return PlacementRequest(
            fabric_id=fabric_id,
            server_hostname=server_hostname(str(service.name.value)) if service.name else "",
            linked_server_id=server.id if server is not None and server.id is not None else None,
            requested_rack_id=service.rack.node.id if service.rack and service.rack.node else None,
            requested_port_id=(
                service.leaf_interface.node.id if service.leaf_interface and service.leaf_interface.node else None
            ),
        )

    async def generate(self, data: dict) -> None:
        parsed = ServerGeneratorQuery(**data)
        service = only_node(
            parsed.network_server_service.edges, of="the server service this generator was dispatched for"
        )

        label = f"server service {service.id}"
        service_name = value_of(service.name, field="name", of=label)
        # Defaulted rather than required: an unset layer means the common case, an L3 attachment.
        layer = service.layer.value if service.layer and service.layer.value else "l3"

        # A hop at a time, so a half-built overlay says which link was missing.
        vrf = related(service.vrf, field="vrf", of=label)
        service_vrf_id = related_id(service.vrf, field="vrf", of=label)
        tenant = related(vrf.tenant, field="tenant", of=f"VRF of {label}")
        fabric_id = related_id(tenant.fabric, field="fabric", of=f"tenant of {label}")

        segment = service.segment.node if service.segment else None
        segment_id = segment.id if segment else None
        segment_vrf_id = segment.vrf.node.id if segment and segment.vrf and segment.vrf.node else None

        # Fail-loud validation BEFORE any object is created (no partial objects): L2 requires a
        # segment in the service's VRF; L3 forbids a segment (contradictory request).
        validate_service(layer, service_name, service_vrf_id, segment_id, segment_vrf_id)

        placement = await self.placement.resolve(self.placement_request(service, fabric_id))

        server = await self.materialize_server(service_name, layer, placement.rack.id)
        server_port = await self.materialize_server_port(server)

        # Free what the new placement supersedes *before* cabling: the server's own port holds a
        # cardinality-1 link, so a stale cable would make the new one unrepresentable.
        await self.placement.release(placement, server_id=server.id, server_port_id=server_port.id)

        await self.cable_server_to_leaf(server, server_port, placement.leaf, placement.leaf_port)

        if layer == "l3":
            await self.configure_l3(server, server_port, placement.leaf, placement.leaf_port, fabric_id)
        else:
            # L2: attach the chosen leaf's rack to the segment's placement. No ASN, no /31, no session —
            # overlay materialization onto the leaf remains the OverlayGenerator's separate step (SD8).
            if segment_id is None:  # validate_service rejects an L2 service with no segment
                msg = f"{label} is L2 but names no segment; validate_service should have rejected it"
                raise ValueError(msg)
            await self.attach_segment_rack(segment_id, placement.rack)

        await self.record_placement(service.id, server.id, placement.rack.id, placement.leaf_port.id)
        await self.update_checksum(service.id, [server.id, server_port.id, placement.leaf_port.id])

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
        """Stamp a content checksum over the materialized object ids on the service.

        Untracked: the service is the operator's design object, not this generator's output.
        """
        service = await self.client.get(kind=NetworkServerService, id=service_id)
        await Checksum.over_contents(object_ids).stamp_on([service], logger=self.logger, track=False)
