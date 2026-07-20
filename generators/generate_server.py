from __future__ import annotations

import hashlib
import logging

from infrahub_sdk.generator import InfrahubGenerator
from infrahub_sdk.protocols import CoreIPPrefixPool, CoreNumberPool

from infrahub_solution_ai_dc.addressing import assign_ip_addresses_to_p2p_connections
from infrahub_solution_ai_dc.generator import GeneratorMixin
from infrahub_solution_ai_dc.protocols import (
    LocationRack,
    NetworkDevice,
    NetworkFabric,
    NetworkInterface,
    NetworkPod,
    NetworkServer,
    NetworkServerService,
)
from infrahub_solution_ai_dc.servers import (
    select_free_server_port,
    select_least_utilized_rack,
    upsert_ebgp_session,
)

from .generate_server_query import ServerGeneratorQuery, ServerGeneratorQueryServiceNode

SERVER_ASN_POOL = "Server ASN Pool"
SERVER_PORT_NAME = "eth1"  # deterministic name of the server's own leaf-facing port
SERVER_P2P_PREFIX_LEN = 31
SERVER_P2P_PREFIX_ROLE = "server_p2p"


class ServerGenerator(InfrahubGenerator, GeneratorMixin):
    """Materialize a ``NetworkServerService`` by attaching a server to a fabric leaf.

    Resolves the request's scope through ``vrf.tenant.fabric``, picks a placement (least-utilized rack +
    lowest free ``role:server`` leaf port), creates the ``NetworkServer`` and its single port, cables it to
    the leaf with a ``NetworkLink``, and — for an L3 service — allocates the server ASN (global pool) and a
    ``server_p2p`` /31 from the pod's ``server_prefix_pool`` and upserts the paired eBGP sessions.

    All operator/service-node writes use ``update_group_context=False`` (mirroring ``OverlayGenerator``) so
    the generator group's cleanup never prunes them. The generator is purely additive/idempotent: the server
    is named deterministically, its own port is looked up by ``(server, name)`` (its ``device`` is null, so
    its ``human_friendly_id`` does not resolve — the ``server`` relationship is the identity instead), the /31
    allocates by a stable identifier, sessions upsert by ``"{a}__{b}"`` name, and the ASN is allocated only
    when unset. Re-running yields an empty diff.

    Extension seams (later chunks): :meth:`resolve_placement` is where explicit ``rack``/``leaf_interface``
    honoring lands (US3/T036); the ``layer == "l3"`` branch in :meth:`generate` is paired with the L2 branch
    (US2/T031) which reuses placement + cabling and instead attaches the chosen rack to the segment.
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

        # Placement: least-utilized rack + lowest free role:server leaf port (fail-loud on none).
        rack, leaf, leaf_port = await self.resolve_placement(service, fabric_id)

        # Shared across L2/L3: create the server, its port, and the server<->leaf link.
        server = await self.materialize_server(service_name, layer, rack.id)
        server_port = await self.materialize_server_port(server)
        await self.cable_server_to_leaf(server, server_port, leaf, leaf_port)

        if layer == "l3":
            await self.configure_l3(server, server_port, leaf, leaf_port, fabric_id)
        else:
            # L2 segment placement (Segment.racks) is deferred to US2/T031; the server + cabling above are
            # already the shared foundation that branch reuses.
            self.logger.info(f"Server service {service_name}: layer l2 attachment deferred to US2 (T031)")

        await self.set_service_server(service.id, server.id)
        await self.update_checksum(service.id, [server.id, server_port.id, leaf_port.id])

    async def resolve_placement(
        self, service: ServerGeneratorQueryServiceNode, fabric_id: str
    ) -> tuple[LocationRack, NetworkDevice, NetworkInterface]:
        """Resolve (rack, leaf, leaf_port) for the attachment.

        L3-core behaviour is fully automatic: pick the least-utilized eligible rack in the fabric, then the
        lowest free ``role:server`` port among that rack's leaves. Explicit ``rack``/``leaf_interface``
        honoring (US3/T036) extends this method; ``service`` is threaded through for that future use.
        """
        _ = service  # explicit placement (rack/leaf_interface) is honored in US3/T036

        rack = await self.select_rack(fabric_id)
        leaf, leaf_port = await self.select_leaf_port(rack)
        self.logger.info(f"Placement: rack {rack.name.value}, leaf {leaf.hostname.value}, port {leaf_port.name.value}")
        return rack, leaf, leaf_port

    async def select_rack(self, fabric_id: str) -> LocationRack:
        """Return the least-utilized rack in the fabric (fewest attached servers), fail-loud if none."""
        pods = await self.client.filters(kind=NetworkPod, parent__ids=[fabric_id])
        pod_ids = [pod.id for pod in pods]
        racks = await self.client.filters(kind=LocationRack, pod__ids=pod_ids) if pod_ids else []

        servers = await self.client.filters(kind=NetworkServer, include=["rack"])
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
            hostname=f"server-{service_name}",
            layer=layer,
            rack={"id": rack_id},
        )
        await server.save(allow_upsert=True, update_group_context=False)
        # Re-fetch so subsequent relationship/pool writes read a fully-resolved node.
        return await self.client.get(kind=NetworkServer, id=server.id)

    async def materialize_server_port(self, server: NetworkServer) -> NetworkInterface:
        """Return the server's own port, looking it up by ``(server, name)`` to stay idempotent.

        The server port has a null ``device`` (it is owned via the ``server`` relationship), so its
        ``human_friendly_id`` does not resolve and ``save(allow_upsert=True)`` cannot match on it. Querying by
        the ``server`` relationship + deterministic ``name`` gives a stable identity across re-runs.
        """
        existing = await self.client.filters(
            kind=NetworkInterface,
            server__ids=[server.id],
            name__value=SERVER_PORT_NAME,
            include=["ip_address", "link"],
        )
        if existing:
            return existing[0]

        port = await self.client.create(
            kind=NetworkInterface,
            name=SERVER_PORT_NAME,
            role="server",
            status="active",
            server={"id": server.id},
        )
        await port.save(allow_upsert=True, update_group_context=False)
        return await self.client.get(kind=NetworkInterface, id=port.id, include=["ip_address", "link"])

    async def cable_server_to_leaf(
        self,
        server: NetworkServer,
        server_port: NetworkInterface,
        leaf: NetworkDevice,
        leaf_port: NetworkInterface,
    ) -> None:
        """Create/upsert the ``NetworkLink`` between the leaf port and the server port.

        Built by hand rather than via ``cabling.connect_interface_maps`` because that helper derives the link
        name from ``interface.device.display_label`` — null on the server-owned port.
        """
        name = f"{leaf.hostname.value}-{leaf_port.name.value}__{server.hostname.value}-{server_port.name.value}"
        link = await self.client.create(
            kind="NetworkLink",
            name=name,
            medium="copper",
            endpoints=[leaf_port, server_port],
        )
        await link.save(allow_upsert=True, update_group_context=False)

        for interface_id in (leaf_port.id, server_port.id):
            interface = await self.client.get(kind=NetworkInterface, id=interface_id, include=["link"])
            interface.status.value = "active"
            await interface.save(allow_upsert=True, update_group_context=False)
        self.logger.info(f"Cabled {name}")

    async def configure_l3(
        self,
        server: NetworkServer,
        server_port: NetworkInterface,
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
        asn = server.asn.value
        if asn is None:
            msg = f"Server ASN pool {SERVER_ASN_POOL!r} did not allocate an ASN (pool exhausted?)"
            raise ValueError(msg)
        return asn

    async def resolve_overlay_asn(self, fabric_id: str) -> int:
        """Return the fabric's overlay ASN (the leaf-side remote AS), fail-loud if not yet allocated."""
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

    async def set_service_server(self, service_id: str, server_id: str) -> None:
        """Point ``service.server`` at the materialized server (generator-set relationship)."""
        service = await self.client.get(kind=NetworkServerService, id=service_id)
        if service.server.id != server_id:
            service.server = {"id": server_id}  # type: ignore[assignment]
            await service.save(allow_upsert=True, update_group_context=False)

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
