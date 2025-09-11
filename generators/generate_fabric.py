from __future__ import annotations

import logging

from infrahub_sdk.generator import InfrahubGenerator
from infrahub_sdk.protocols import CoreIPAddressPool, CoreIPPrefixPool

from solution_ai_dc.generator import GeneratorMixin
from solution_ai_dc.protocols import NetworkDevice, NetworkInterface, NetworkPod


class FabricGenerator(InfrahubGenerator, GeneratorMixin):
    fabric_name: str
    fabric_id: str

    loopback_pool: CoreIPAddressPool

    log = logging.getLogger("infrahub.tasks")

    async def generate(self, data: dict) -> None:
        self.fabric_name = data["NetworkFabric"]["edges"][0]["node"]["name"]["value"].lower()
        self.fabric_id = data["NetworkFabric"]["edges"][0]["node"]["id"]
        self.amount_of_super_spines = data["NetworkFabric"]["edges"][0]["node"]["amount_of_super_spines"]["value"]

        await self.allocate_resource_pools()

        await self.create_super_spine_switches()

        await self.update_checksum()

    async def create_super_spine_switches(self) -> None:
        fabric_pod = await self.client.get(kind=NetworkPod, parent__ids=[self.fabric_id], role__value="fabric")

        for idx in range(1, self.amount_of_super_spines + 1):
            device = await self.client.create(
                NetworkDevice,
                hostname=f"ss-{self.fabric_name}-{idx}",
                object_template={"hfid": ["Super Spine Switch"]},
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
            loopback_interface.ip_address = device.loopback_ip.id
            await loopback_interface.save(allow_upsert=True)

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
