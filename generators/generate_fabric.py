from __future__ import annotations

import logging

from infrahub_sdk.generator import InfrahubGenerator
from infrahub_sdk.protocols import CoreIPAddressPool, CoreIPPrefixPool

from solution_ai_dc.generator import GeneratorMixin
from solution_ai_dc.protocols import NetworkDevice, NetworkPod, NetworkPodBuilder


class FabricGenerator(InfrahubGenerator, GeneratorMixin):
    fabric_name: str
    fabric_id: str

    loopback_pool: CoreIPAddressPool

    log = logging.getLogger("infrahub.tasks")

    async def generate(self, data: dict) -> None:
        self.fabric_name = data["NetworkFabric"]["edges"][0]["node"]["name"]["value"].lower()
        self.fabric_id = data["NetworkFabric"]["edges"][0]["node"]["id"]

        await self.allocate_resource_pools()

        fabric_pod = await self.client.get(kind=NetworkPod, parent__ids=[self.fabric_id], role__value="fabric")

        for idx in range(1, 7):
            device = await self.client.create(
                NetworkDevice,
                hostname=f"ss-{self.fabric_name}-{idx}",
                object_template={"hfid": ["Super Spine Switch"]},
                loopback_ip=self.loopback_pool,
                role="super_spine",
                pod=fabric_pod,
            )
            await device.save(allow_upsert=True)

        pods = await self.client.filters(kind=NetworkPod, parent__ids=[self.fabric_id])
        pod_builders = await self.client.filters(kind=NetworkPodBuilder, target__ids=[pod.id for pod in pods])

        # store the checksum for the fabric in the object itself
        fabric_checksum = self.calculate_checksum()
        for pod_builder in pod_builders:
            if pod_builder.checksum.value != fabric_checksum:
                pod_builder.checksum.value = fabric_checksum
                await pod_builder.save(allow_upsert=True)
                self.logger.info(f"Generator builder {pod_builder.id} has been updated to checksum {fabric_checksum}")

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
