from __future__ import annotations

import logging

from infrahub_sdk.generator import InfrahubGenerator
from infrahub_sdk.protocols import CoreIPAddressPool, CoreIPPrefixPool

from solution_ai_dc.addressing import assign_ip_addresses_to_p2p_connections
from solution_ai_dc.cabling import build_cabling_plan, connect_interface_maps
from solution_ai_dc.protocols import NetworkDevice, NetworkInterface
from solution_ai_dc.sorting import create_sorted_device_interface_map

EXCLUDED_RACK_TYPES = []

LEAF_TEMPLATE_MAP = {
    "compute": "leaf-switch-compute",
    "storage": "leaf-switch-storage",
}


class RackGenerator(InfrahubGenerator):
    rack_id: str
    rack_index: int
    rack_name: str

    pod_id: str
    pod_index: int
    pod_name: str

    spine_switches: list[NetworkDevice]

    leaf_switch: NetworkDevice

    loopback_pool: CoreIPAddressPool
    prefix_pool: CoreIPPrefixPool

    logger = logging.getLogger("infrahub.tasks")

    async def generate(self, data: dict) -> None:
        self.rack_id: str = data["LocationRack"]["edges"][0]["node"]["id"]
        self.rack_index: int = data["LocationRack"]["edges"][0]["node"]["index"]["value"]
        self.rack_name: str = data["LocationRack"]["edges"][0]["node"]["name"]["value"]
        self.rack_type: str = data["LocationRack"]["edges"][0]["node"]["rack_type"]["value"]

        self.pod_id: str = data["LocationRack"]["edges"][0]["node"]["pod"]["node"]["id"]
        self.pod_index: int = data["LocationRack"]["edges"][0]["node"]["pod"]["node"]["index"]["value"]
        self.pod_name: str = data["LocationRack"]["edges"][0]["node"]["pod"]["node"]["name"]["value"].lower()
        self.pod_amount_of_spines: int = data["LocationRack"]["edges"][0]["node"]["pod"]["node"]["amount_of_spines"][
            "value"
        ]

        self.loopback_pool_id: str = data["LocationRack"]["edges"][0]["node"]["pod"]["node"]["loopback_pool"]["node"][
            "id"
        ]
        self.prefix_pool_id: str = data["LocationRack"]["edges"][0]["node"]["pod"]["node"]["prefix_pool"]["node"]["id"]

        self.loopback_pool = await self.client.get(kind=CoreIPAddressPool, id=self.loopback_pool_id)
        self.prefix_pool = await self.client.get(kind=CoreIPPrefixPool, id=self.prefix_pool_id)

        self.spine_switches = await self.client.filters(kind=NetworkDevice, pod__ids=[self.pod_id], role__value="spine")

        if self.rack_type in EXCLUDED_RACK_TYPES:
            msg = f"Cannot run rack generator on {self.rack_name}-{self.rack_id}: {self.rack_type} is not supported by the generator!"
            raise ValueError(msg)

        if self.pod_amount_of_spines != len(self.spine_switches):
            msg = f"Cannot start rack generator on {self.rack_name}-{self.rack_id}: the pod doesn't seem to be fully generated"
            raise RuntimeError(msg)

        await self.create_leaf_switch()

        await self.connect_leaf_to_spine()

    async def create_leaf_switch(self) -> None:
        self.leaf_switch = await self.client.create(
            NetworkDevice,
            hostname=f"leaf-{self.pod_name}-{self.rack_index}",
            object_template={"hfid": [LEAF_TEMPLATE_MAP[self.rack_type]]},
            pod={"id": self.pod_id},
            rack={"id": self.rack_id},
            loopback_ip=self.loopback_pool,
            role="leaf",
        )
        await self.leaf_switch.save(allow_upsert=True)

    async def connect_leaf_to_spine(self) -> None:
        spine_interfaces = await self.client.filters(
            kind=NetworkInterface, device__ids=[spine.id for spine in self.spine_switches], role__value="leaf"
        )
        spine_interface_map = create_sorted_device_interface_map(spine_interfaces)

        leaf_interfaces = await self.client.filters(
            kind=NetworkInterface, device__ids=[self.leaf_switch.id], role__value="spine"
        )
        leaf_interface_map = create_sorted_device_interface_map(leaf_interfaces)

        created_cabling_plan: list[tuple[NetworkInterface, NetworkInterface]] = build_cabling_plan(
            logger=self.logger,
            pod_index=self.rack_index,
            src_interface_map=leaf_interface_map,
            dst_interface_map=spine_interface_map,
        )

        await connect_interface_maps(client=self.client, logger=self.logger, cabling_plan=created_cabling_plan)

        await assign_ip_addresses_to_p2p_connections(
            client=self.client,
            logger=self.logger,
            connections=created_cabling_plan,
            prefix_len=31,
            prefix_role="pod_leaf_spine",
            pool=self.prefix_pool,
        )
