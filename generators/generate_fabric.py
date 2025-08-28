from __future__ import annotations

import logging
import random

from infrahub_sdk.generator import InfrahubGenerator
from infrahub_sdk.node import InfrahubNode


class FabricGenerator(InfrahubGenerator):

    log = logging.getLogger("infrahub.tasks")

    async def generate(self, data: dict) -> None:

        # generic_switch_tpl = await self.client.get(kind="TemplateNetworkDevice", template_name__value="Generic Switch")

        fabric_name: str = data["NetworkFabric"]["edges"][0]["node"]["name"]["value"]

        for idx in range(1, 5):
            device = await self.client.create(
                "NetworkDevice",
                hostname=f"ss-{fabric_name.lower()}-{idx}",
                object_template={ "hfid": ["Generic Switch"]}, #generic_switch_tpl,
                role="super_spine"
            )
            await device.save(allow_upsert=True)

