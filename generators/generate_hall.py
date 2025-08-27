from __future__ import annotations

import logging
import random

from infrahub_sdk.generator import InfrahubGenerator
from infrahub_sdk.node import InfrahubNode


class HallGenerator(InfrahubGenerator):

    log = logging.getLogger("infrahub.tasks")

    async def generate(self, data: dict) -> None:

        hall_name: str = data["NetworkHall"]["edges"][0]["node"]["name"]["value"]

        for idx in range(0, 5):
            device = await self.client.create("NetworkDevice", name=f"fabric-{hall_name}-{idx}", template="Generic Switch")
            await device.save(allow_upsert=True)

