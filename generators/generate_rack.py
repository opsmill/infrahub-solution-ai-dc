from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from infrahub_sdk.generator import InfrahubGenerator  # type: ignore[import-not-found]
from infrahub_sdk.protocols import CoreIPAddressPool, CoreIPPrefixPool  # type: ignore[import-not-found]

from infrahub_solution_ai_dc import sorting
from infrahub_solution_ai_dc.addressing import assign_ip_addresses_to_p2p_connections
from infrahub_solution_ai_dc.cabling import build_rack_cabling_plan, connect_interface_maps
from infrahub_solution_ai_dc.protocols import NetworkDevice, NetworkInterface

from .rack_generator_query import RackGeneratorQuery

if TYPE_CHECKING:
    from collections.abc import Callable

EXCLUDED_RACK_TYPES: list[str] = []


class RackGenerator(InfrahubGenerator):
    rack_id: str
    rack_index: int
    rack_name: str
    rack_leaf_switch_template: str
    rack_amount_of_leafs: int

    spine_interface_sorting_function: Callable
    leaf_interface_sorting_function: Callable

    pod_id: str
    pod_index: int
    pod_name: str

    spine_switches: list[NetworkDevice]

    leaf_switches: list[NetworkDevice]

    loopback_pool: CoreIPAddressPool
    prefix_pool: CoreIPPrefixPool

    logger = logging.getLogger("infrahub.tasks")

    async def generate(self, data: dict) -> None:
        parsed = RackGeneratorQuery(**data)
        rack = parsed.location_rack.edges[0].node
        assert rack is not None

        self.rack_id: str = rack.id
        self.rack_index: int = rack.index.value  # type: ignore[union-attr, assignment]
        self.rack_name: str = rack.name.value  # type: ignore[union-attr, assignment]
        self.rack_type: str = rack.rack_type.value  # type: ignore[union-attr, assignment]
        self.rack_leaf_switch_template: str = rack.leaf_switch_template.node.id  # type: ignore[union-attr, assignment]
        self.rack_amount_of_leafs: int = rack.amount_of_leafs.value  # type: ignore[union-attr, assignment]
        self.leaf_switches = []

        self.pod_id: str = rack.pod.node.id  # type: ignore[union-attr]
        self.pod_index: int = rack.pod.node.index.value  # type: ignore[union-attr, assignment]
        self.pod_name: str = rack.pod.node.name.value.lower()  # type: ignore[union-attr]
        self.pod_amount_of_spines: int = rack.pod.node.amount_of_spines.value  # type: ignore[union-attr, assignment]

        self.loopback_pool_id: str = rack.pod.node.loopback_pool.node.id  # type: ignore[union-attr]
        self.prefix_pool_id: str = rack.pod.node.prefix_pool.node.id  # type: ignore[union-attr]

        self.loopback_pool = await self.client.get(kind=CoreIPAddressPool, id=self.loopback_pool_id)
        self.prefix_pool = await self.client.get(kind=CoreIPPrefixPool, id=self.prefix_pool_id)

        self.spine_switches = await self.client.filters(kind=NetworkDevice, pod__ids=[self.pod_id], role__value="spine")

        if self.rack_type in EXCLUDED_RACK_TYPES:
            msg = f"Cannot run rack generator on {self.rack_name}-{self.rack_id}: {self.rack_type} is not supported by the generator!"
            raise ValueError(msg)

        if self.pod_amount_of_spines != len(self.spine_switches):
            msg = f"Cannot start rack generator on {self.rack_name}-{self.rack_id}: the pod doesn't seem to be fully generated"
            raise RuntimeError(msg)

        leaf_interface_sorting_method: str = rack.pod.node.leaf_interface_sorting_method.value  # type: ignore[union-attr, assignment]
        spine_interface_sorting_method: str = rack.pod.node.spine_interface_sorting_method.value  # type: ignore[union-attr, assignment]

        self.leaf_interface_sorting_function = getattr(sorting, leaf_interface_sorting_method)
        self.spine_interface_sorting_function = getattr(sorting, spine_interface_sorting_method)

        await self.create_leaf_switches()

        await self.connect_leafs_to_spine()

    async def create_leaf_switches(self) -> None:
        for index in range(1, self.rack_amount_of_leafs + 1):
            leaf_switch = await self.client.create(
                NetworkDevice,
                hostname=f"leaf-{self.pod_name}-{self.rack_index}-{index}",
                object_template={"id": self.rack_leaf_switch_template},
                pod={"id": self.pod_id},
                rack={"id": self.rack_id},
                loopback_ip=self.loopback_pool,
                index=index,
                role="leaf",
                member_of_groups=["devices"],
            )
            await leaf_switch.save(allow_upsert=True)
            self.leaf_switches.append(leaf_switch)

            # FIX: seems the id of a related node assigned from a pool is not immediately accessible
            device = await self.client.get(
                NetworkDevice,
                id=leaf_switch.id,
                include=["ip_address"],
                exclude=["rack", "pod", "role", "hostname", "object_template", "member_of_groups"],
            )
            loopback_interface = await self.client.get(
                NetworkInterface, device__ids=[device.id], role__value="loopback"
            )
            loopback_interface.status.value = "active"
            loopback_interface.ip_address = device.loopback_ip.id
            await loopback_interface.save(allow_upsert=True)

    async def connect_leafs_to_spine(self) -> None:
        spine_interfaces = await self.client.filters(
            kind=NetworkInterface, device__ids=[spine.id for spine in self.spine_switches], role__value="leaf"
        )
        spine_interface_map = self.spine_interface_sorting_function(spine_interfaces)

        leaf_interfaces = await self.client.filters(
            kind=NetworkInterface,
            device__ids=[leaf_switch.id for leaf_switch in self.leaf_switches],
            role__value="spine",
        )
        leaf_interface_map = self.leaf_interface_sorting_function(leaf_interfaces)

        created_cabling_plan: list[tuple[NetworkInterface, NetworkInterface]] = build_rack_cabling_plan(
            rack_index=self.rack_index,
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
