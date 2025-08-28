from __future__ import annotations

import logging
import random

from infrahub_sdk.generator import InfrahubGenerator
from infrahub_sdk.node import InfrahubNode


class FabricGenerator(InfrahubGenerator):

    log = logging.getLogger("infrahub.tasks")

    async def generate(self, data: dict) -> None:

        # generic_switch_tpl = await self.client.get(kind="TemplateNetworkDevice", template_name__value="Generic Switch")

        fabric_name: str = data["NetworkFabric"]["edges"][0]["node"]["name"]["value"].lower()
        fabric_id: str = data["NetworkFabric"]["edges"][0]["node"]["id"]

        fabric_supernet_pool = await self.client.get(kind="CoreIPPrefixPool", name__value="FabricSupernetPool")
        fabric_supernet = await self.client.allocate_next_ip_prefix(
            resource_pool=fabric_supernet_pool,
            identifier=fabric_id,
            data={
                "role": "fabric_supernet"
            }
        )

        fabric_prefix_pool = await self.client.create(
            kind="CoreIPPrefixPool",
            name=f"{fabric_name}-prefix-pool",
            default_prefix_type = "IpamIPPrefix",
            default_prefix_length = 24,
            ip_namespace = {"hfid": ["default"]},
            resources = [fabric_supernet]
        )

        await fabric_prefix_pool.save(allow_upsert=True)

        ss_loopback_prefix = await self.client.allocate_next_ip_prefix(
            resource_pool=fabric_prefix_pool,
            identifier=fabric_id,
            member_type="address",
            prefix_length=28,
            data={
                "role": "super_spine_loopback"
            }
        )

        ss_loopback_pool = await self.client.create(
            kind="CoreIPAddressPool",
            name=f"{fabric_name}-super-spine-loopback-pool",
            default_address_type = "IpamIPAddress",
            default_prefix_length = 32,
            ip_namespace = {"hfid": ["default"]},
            resources = [fabric_supernet]
        )

        await ss_loopback_pool.save(allow_upsert=True)

        fabric_pod = await self.client.get(kind="NetworkPod", parent__ids=[fabric_id], role__value="fabric")

        for idx in range(1, 5):
            device = await self.client.create(
                "NetworkDevice",
                hostname=f"ss-{fabric_name}-{idx}",
                object_template={ "hfid": ["Super Spine Switch"]},
                loopback_ip=ss_loopback_pool,
                role="super_spine",
                pod=fabric_pod
            )
            await device.save(allow_upsert=True)

