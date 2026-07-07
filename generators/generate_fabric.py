from __future__ import annotations

import logging

from infrahub_sdk.generator import InfrahubGenerator
from infrahub_sdk.protocols import CoreIPAddressPool, CoreIPPrefixPool, CoreNumberPool

from infrahub_solution_ai_dc.generator import GeneratorMixin
from infrahub_solution_ai_dc.protocols import NetworkDevice, NetworkFabric, NetworkInterface, NetworkPod

from .fabric_generator_query import FabricGeneratorQuery

ASN_POOL_NAME = "Overlay ASN Pool"
DEFAULT_ROUTING_DESIGN = "ibgp_evpn_ospf_underlay"


class FabricGenerator(InfrahubGenerator, GeneratorMixin):
    fabric_name: str
    fabric_id: str
    fabric_super_spine_switch_template: str
    amount_of_super_spines: int

    loopback_pool: CoreIPAddressPool
    super_spine_switches: list[NetworkDevice]

    logger = logging.getLogger("infrahub.tasks")

    async def generate(self, data: dict) -> None:
        parsed = FabricGeneratorQuery(**data)
        fabric = parsed.network_fabric.edges[0].node
        assert fabric is not None

        self.fabric_name = fabric.name.value.lower()  # type: ignore[union-attr]
        self.fabric_id = fabric.id
        self.fabric_super_spine_switch_template = fabric.super_spine_switch_template.node.id  # type: ignore[union-attr, assignment]
        self.amount_of_super_spines = fabric.amount_of_super_spines.value  # type: ignore[union-attr, assignment]
        self.super_spine_switches = []

        await self.allocate_resource_pools()

        await self.create_super_spine_switches()

        await self.update_checksum()

        # Overlay device-attribute work runs AFTER the physical checksum so that allocating overlay_asn and
        # stamping device.asn does not change the fabric checksum and re-trigger the pod/rack cascade (ADR-0004).
        await self.configure_overlay()

    async def create_super_spine_switches(self) -> None:
        fabric_pod = await self.client.get(kind=NetworkPod, parent__ids=[self.fabric_id], role__value="fabric")

        for idx in range(1, self.amount_of_super_spines + 1):
            device = await self.client.create(
                NetworkDevice,
                hostname=f"ss-{self.fabric_name}-{idx}",
                object_template={"id": self.fabric_super_spine_switch_template},
                loopback_ip=self.loopback_pool,
                role="super_spine",
                pod=fabric_pod,
                member_of_groups=["devices"],
            )
            await device.save(allow_upsert=True)

            # FIX: seems the id of a related node assigned from a pool is not immediately accessible
            device = await self.client.get(
                NetworkDevice,
                id=device.id,
                include=["ip_address"],
                exclude=["rack", "pod", "role", "hostname", "object_template", "member_of_groups"],
            )
            loopback_interface = await self.client.get(
                NetworkInterface, device__ids=[device.id], role__value="loopback"
            )
            loopback_interface.status.value = "active"
            loopback_interface.ip_address = device.loopback_ip.id  # type: ignore[assignment]
            await loopback_interface.save(allow_upsert=True)

            self.super_spine_switches.append(device)

    async def configure_overlay(self) -> None:
        """Allocate the fabric overlay ASN (once) and stamp it on every super-spine (iBGP: device.asn == overlay_asn).

        Allocation is guarded ("only if unset") because ``from_pool`` is not guaranteed idempotent across re-runs,
        and this runs after ``update_checksum`` so it never re-triggers the physical cascade.
        """
        fabric = await self.client.get(kind=NetworkFabric, id=self.fabric_id)

        if fabric.overlay_asn.value is None:
            asn_pool = await self.client.get(kind=CoreNumberPool, name__value=ASN_POOL_NAME)
            fabric.overlay_asn.value = asn_pool  # type: ignore[assignment]  # number pool -> server-side from_pool allocation
            if not fabric.routing_design.value:
                fabric.routing_design.value = DEFAULT_ROUTING_DESIGN
            await fabric.save(allow_upsert=True)
            # FIX: a value allocated from a pool is not readable on the returned node; re-fetch to read it
            fabric = await self.client.get(kind=NetworkFabric, id=self.fabric_id)
        elif not fabric.routing_design.value:
            fabric.routing_design.value = DEFAULT_ROUTING_DESIGN
            await fabric.save(allow_upsert=True)

        overlay_asn = fabric.overlay_asn.value
        if overlay_asn is None:
            self.logger.warning(f"Could not resolve overlay_asn for fabric {self.fabric_name}; skipping ASN stamping")
            return

        for super_spine in self.super_spine_switches:
            device = await self.client.get(kind=NetworkDevice, id=super_spine.id)
            if device.asn.value != overlay_asn or not device.route_reflector.value:
                device.asn.value = overlay_asn
                device.route_reflector.value = True
                await device.save(allow_upsert=True)
                self.logger.info(f"Stamped ASN {overlay_asn} (route reflector) on {device.hostname.value}")

    async def allocate_resource_pools(self) -> None:
        fabric_supernet_pool = await self.client.get(kind=CoreIPPrefixPool, name__value="FabricSupernetPool")
        fabric_supernet = await self.client.allocate_next_ip_prefix(
            resource_pool=fabric_supernet_pool, identifier=self.fabric_id, data={"role": "fabric_supernet"}
        )

        fabric_prefix_pool = await self.client.create(
            kind=CoreIPPrefixPool,
            name=f"{self.fabric_name}-prefix-pool",
            default_prefix_type="IpamIPPrefix",
            default_prefix_length=24,
            ip_namespace={"hfid": ["default"]},
            resources=[fabric_supernet],
        )
        await fabric_prefix_pool.save(allow_upsert=True)

        ss_loopback_prefix = await self.client.allocate_next_ip_prefix(
            resource_pool=fabric_prefix_pool,
            identifier=self.fabric_id,
            member_type="address",
            prefix_length=28,
            data={"role": "super_spine_loopback"},
        )

        self.loopback_pool = await self.client.create(
            kind=CoreIPAddressPool,
            name=f"{self.fabric_name}-super-spine-loopback-pool",
            default_address_type="IpamIPAddress",
            default_prefix_length=32,
            ip_namespace={"hfid": ["default"]},
            resources=[ss_loopback_prefix],
        )
        await self.loopback_pool.save(allow_upsert=True)

    async def update_checksum(self) -> None:
        pods = await self.client.filters(kind=NetworkPod, parent__ids=[self.fabric_id])

        # store the checksum for the fabric in the object itself
        fabric_checksum = self.calculate_checksum()
        for pod in pods:
            if pod.checksum.value != fabric_checksum:
                pod.checksum.value = fabric_checksum
                await pod.save(allow_upsert=True)
                self.logger.info(f"Pod {pod.name.value} has been updated to checksum {fabric_checksum}")
