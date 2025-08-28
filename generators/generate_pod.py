from __future__ import annotations

import logging

from infrahub_sdk.generator import InfrahubGenerator
from infrahub_sdk.node import InfrahubNode


class PodGenerator(InfrahubGenerator):

    log = logging.getLogger("infrahub.tasks")

    async def generate(self, data: dict) -> None:

        pod_name: str = data["NetworkPod"]["edges"][0]["node"]["name"]["value"]

        # Create the spine switches
        for idx in range(1, 5):
            device = await self.client.create(
                "NetworkDevice",
                hostname=f"spine-{pod_name}-{idx}",
                template="Generic Switch",
                role="spine"
            )
            await device.save(allow_upsert=True)

        # Connect the Spine to the SuperSpine

