from __future__ import annotations

import logging

from infrahub_sdk.generator import InfrahubGenerator


class RackGenerator(InfrahubGenerator):
    logger = logging.getLogger("infrahub.tasks")

    async def generate(self, data: dict) -> None:
        pass

        # Generate the leaf device
        # Connect it to the spines

