from __future__ import annotations

import logging

from collections import defaultdict
from typing import Dict, List

from infrahub_sdk import InfrahubClient
from infrahub_sdk.generator import InfrahubGenerator
from infrahub_sdk.node import InfrahubNode


class RackGenerator(InfrahubGenerator):

    logger = logging.getLogger("infrahub.tasks")

    async def generate(self, data: dict) -> None:
        pass
