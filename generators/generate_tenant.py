from __future__ import annotations

import hashlib
import logging

from infrahub_sdk.generator import InfrahubGenerator
from infrahub_sdk.protocols import CoreIPPrefixPool, CoreNumberPool

from infrahub_solution_ai_dc.generator import GeneratorMixin
from infrahub_solution_ai_dc.overlay import resolve_segment_devices, route_target
from infrahub_solution_ai_dc.protocols import (
    NetworkDevice,
    NetworkFabric,
    NetworkPod,
    NetworkSegment,
    NetworkTenant,
    NetworkVrf,
)

from .generate_tenant_query import (
    TenantGeneratorQuery,
    TenantGeneratorQuerySegmentNode,
    TenantGeneratorQueryVrfNode,
)

L2VNI_POOL = "L2VNI Pool"
L3VNI_POOL = "L3VNI Pool"
VLAN_L2_POOL = "VLAN L2 Pool"
VLAN_L3_POOL = "VLAN L3 Pool"
TENANT_SUBNET_POOL = "TenantSubnetPool"
GATEWAY_HOST_INDEX = 1  # anycast gateway = .1 of the segment subnet


class OverlayGenerator(InfrahubGenerator, GeneratorMixin):
    """Materialize a tenant's EVPN overlay: allocate VNIs/VLANs/RTs/subnets and place segments on leafs.

    Allocates overlay identifiers from Resource Manager pools (guarded "only if unset"), sets generator-owned
    route targets, allocates an anycast-gateway subnet for routed (IRB) segments, and writes ``Device.segments``
    onto the carrying leafs (placement intent resolved via ``overlay.resolve_segment_devices``). Spines and
    super-spines never receive ``segments`` and therefore render no tenant state.

    Every mutation is done with ``update_group_context=False``: the operator-owned tenancy nodes and the
    physical leafs this generator modifies must never be pruned by the generator group's ``delete_unused_nodes``
    cleanup. The generator is purely additive/idempotent; releasing identifiers on removal is handled
    explicitly (US2).
    """

    tenant_id: str
    tenant_name: str
    fabric_id: str

    logger = logging.getLogger("infrahub.tasks")

    async def generate(self, data: dict) -> None:
        parsed = TenantGeneratorQuery(**data)
        tenant = parsed.network_tenant.edges[0].node
        assert tenant is not None
        assert tenant.fabric is not None
        assert tenant.fabric.node is not None

        self.tenant_id = tenant.id
        self.tenant_name = tenant.name.value if tenant.name and tenant.name.value is not None else tenant.id
        self.fabric_id = tenant.fabric.node.id

        overlay_asn = await self.resolve_overlay_asn(tenant.fabric.node.overlay_asn)
        if overlay_asn is None:
            self.logger.warning(
                f"Tenant {self.tenant_name}: fabric overlay_asn is not allocated yet; deferring overlay generation"
            )
            return

        leafs_by_rack = await self.leafs_by_rack()
        leaf_total = sum(len(leafs) for leafs in leafs_by_rack.values())
        self.logger.info(f"Tenant {self.tenant_name}: {leaf_total} fabric leaf(s) across {len(leafs_by_rack)} rack(s)")

        vrf_nodes = [edge.node for edge in tenant.vrfs.edges if edge.node] if tenant.vrfs else []

        # Desired placement across the whole tenant: device id -> set of segment ids it must carry.
        desired: dict[str, set[str]] = {}
        tenant_segment_ids: set[str] = set()

        for vrf_node in vrf_nodes:
            await self.configure_vrf(vrf_node, overlay_asn)
            segment_nodes = [edge.node for edge in vrf_node.segments.edges if edge.node] if vrf_node.segments else []
            for segment_node in segment_nodes:
                tenant_segment_ids.add(segment_node.id)
                await self.configure_segment(segment_node, overlay_asn)
                rack_ids = (
                    [edge.node.id for edge in segment_node.racks.edges if edge.node] if segment_node.racks else []
                )
                for device in resolve_segment_devices(rack_ids, leafs_by_rack):
                    desired.setdefault(device.id, set()).add(segment_node.id)

        self.logger.info(
            f"Tenant {self.tenant_name}: {len(tenant_segment_ids)} segment(s); placement on {len(desired)} leaf(s)"
        )
        await self.materialize_segments(leafs_by_rack, desired, tenant_segment_ids)

        await self.update_checksum(tenant_segment_ids)

    async def resolve_overlay_asn(self, queried_overlay_asn: object) -> int | None:
        """Return the fabric overlay ASN, re-fetching the fabric if the queried value is stale (None)."""
        value = getattr(queried_overlay_asn, "value", None)
        if value is not None:
            return value
        fabric = await self.client.get(kind=NetworkFabric, id=self.fabric_id)
        return fabric.overlay_asn.value

    async def leafs_by_rack(self) -> dict[str, list[NetworkDevice]]:
        """Group every leaf in the tenant's fabric by its rack id (the placement universe)."""
        pods = await self.client.filters(kind=NetworkPod, parent__ids=[self.fabric_id])
        pod_ids = [pod.id for pod in pods]
        result: dict[str, list[NetworkDevice]] = {}
        if not pod_ids:
            return result
        leafs = await self.client.filters(kind=NetworkDevice, role__value="leaf", pod__ids=pod_ids, include=["rack"])
        for leaf in leafs:
            rack_id = leaf.rack.id
            if rack_id is not None:
                result.setdefault(rack_id, []).append(leaf)
        return result

    async def configure_vrf(self, vrf_node: TenantGeneratorQueryVrfNode, overlay_asn: int) -> None:
        """Allocate l3vni + l3_vlan_id from pools (once) and set the VRF route target (<asn>:<l3vni>)."""
        vrf = await self.client.get(kind=NetworkVrf, id=vrf_node.id)
        changed = False
        if vrf.l3vni.value is None:
            vrf.l3vni.value = await self.client.get(kind=CoreNumberPool, name__value=L3VNI_POOL)  # type: ignore[assignment]
            changed = True
        if vrf.l3_vlan_id.value is None:
            vrf.l3_vlan_id.value = await self.client.get(kind=CoreNumberPool, name__value=VLAN_L3_POOL)  # type: ignore[assignment]
            changed = True
        if changed:
            await vrf.save(allow_upsert=True, update_group_context=False)
            # FIX: pool-allocated values are not readable on the returned node; re-fetch to read them
            vrf = await self.client.get(kind=NetworkVrf, id=vrf_node.id)

        rt = route_target(overlay_asn, vrf.l3vni.value)  # type: ignore[arg-type]
        if vrf.route_target.value != rt:
            vrf.route_target.value = rt
            await vrf.save(allow_upsert=True, update_group_context=False)

    async def configure_segment(self, segment_node: TenantGeneratorQuerySegmentNode, overlay_asn: int) -> None:
        """Allocate vlan_id + l2vni (once), set the segment route target, and allocate an IRB subnet/gateway."""
        segment = await self.client.get(kind=NetworkSegment, id=segment_node.id)
        changed = False
        if segment.vlan_id.value is None:
            segment.vlan_id.value = await self.client.get(kind=CoreNumberPool, name__value=VLAN_L2_POOL)  # type: ignore[assignment]
            changed = True
        if segment.l2vni.value is None:
            segment.l2vni.value = await self.client.get(kind=CoreNumberPool, name__value=L2VNI_POOL)  # type: ignore[assignment]
            changed = True
        if changed:
            await segment.save(allow_upsert=True, update_group_context=False)
            # FIX: pool-allocated values are not readable on the returned node; re-fetch to read them
            segment = await self.client.get(kind=NetworkSegment, id=segment_node.id)

        rt = route_target(overlay_asn, segment.l2vni.value)  # type: ignore[arg-type]
        if segment.route_target.value != rt:
            segment.route_target.value = rt
            await segment.save(allow_upsert=True, update_group_context=False)

        routed = segment.routed.value if segment.routed.value is not None else True
        if routed and segment.subnet.id is None:
            await self.allocate_subnet_and_gateway(segment)

    async def allocate_subnet_and_gateway(self, segment: NetworkSegment) -> None:
        """Allocate a tenant_subnet prefix for an IRB segment and create its .1 anycast gateway address."""
        pool = await self.client.get(kind=CoreIPPrefixPool, name__value=TENANT_SUBNET_POOL)
        subnet = await self.client.allocate_next_ip_prefix(
            resource_pool=pool,
            identifier=segment.id,
            member_type="address",
            prefix_length=24,
            data={"role": "tenant_subnet"},
        )

        network = subnet.prefix.value  # type: ignore[union-attr]
        gateway_ip = list(network.hosts())[GATEWAY_HOST_INDEX - 1]
        gateway = await self.client.create(kind="IpamIPAddress", address=f"{gateway_ip}/{network.prefixlen}")
        await gateway.save(allow_upsert=True, update_group_context=False)

        segment.subnet = subnet  # type: ignore[assignment]
        segment.gateway = gateway  # type: ignore[assignment]
        await segment.save(allow_upsert=True, update_group_context=False)
        self.logger.info(f"Allocated subnet {network} (gw {gateway_ip}) for segment {segment.name.value}")

    async def materialize_segments(
        self,
        leafs_by_rack: dict[str, list[NetworkDevice]],
        desired: dict[str, set[str]],
        tenant_segment_ids: set[str],
    ) -> None:
        """Reconcile ``Device.segments`` on every fabric leaf, merging this tenant's placement with others'.

        Only leafs whose segment set actually changes are saved, so unrelated devices' artifacts stay byte
        identical (scoped regeneration — US2). Segments belonging to other tenants are preserved.
        """
        for leafs in leafs_by_rack.values():
            for leaf in leafs:
                device = await self.client.get(kind=NetworkDevice, id=leaf.id, include=["segments"])
                current = {peer.id for peer in device.segments.peers if peer.id is not None}
                keep_other_tenants = current - tenant_segment_ids
                new_set = keep_other_tenants | desired.get(leaf.id, set())
                if new_set != current:
                    for segment_id in new_set - current:
                        device.segments.add(segment_id)
                    for segment_id in current - new_set:
                        device.segments.remove(segment_id)
                    await device.save(allow_upsert=True, update_group_context=False)
                    self.logger.info(f"Updated segments on {device.hostname.value}: {len(new_set)} segment(s)")

    async def update_checksum(self, tenant_segment_ids: set[str]) -> None:
        """Stamp a content checksum (over the tenant's segment set) on the tenant for change visibility.

        Stamped with ``update_group_context=False`` so the tenant is not tracked, and only when it changes so an
        unchanged re-run is a no-op (no self-retrigger loop).
        """
        payload = ",".join(sorted(tenant_segment_ids))
        checksum = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        tenant = await self.client.get(kind=NetworkTenant, id=self.tenant_id)
        if tenant.checksum.value != checksum:
            tenant.checksum.value = checksum
            await tenant.save(allow_upsert=True, update_group_context=False)
