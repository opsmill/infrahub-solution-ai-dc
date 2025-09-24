from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from infrahub_sdk.generator import InfrahubGenerator
from infrahub_sdk.protocols import CoreIPAddressPool, CoreIPPrefixPool

from solution_ai_dc import sorting as solution_ai_dc_sorting
from solution_ai_dc.addressing import assign_ip_addresses_to_p2p_connections
from solution_ai_dc.cabling import build_pod_cabling_plan, connect_interface_maps
from solution_ai_dc.generator import GeneratorMixin
from solution_ai_dc.protocols import LocationRack, NetworkDevice, NetworkInterface, NetworkPod

from .pod_generator_query import PodGeneratorQuery

if TYPE_CHECKING:
    from collections.abc import Callable

EXCLUDED_POD_ROLES = ["fabric"]


class PodGenerator(InfrahubGenerator, GeneratorMixin):
    pod_id: str
    pod_index: int
    pod_name: str
    pod_spine_switch_template: str
    pod_role: str

    fabric_interface_sorting_function: Callable
    spine_interface_sorting_function: Callable

    fabric_id: str
    fabric_name: str

    loopback_pool: CoreIPAddressPool

    pod_prefix_pool: CoreIPPrefixPool
    spine_switches: list[NetworkDevice]
    super_spine_switches: list[NetworkDevice]

    logger = logging.getLogger("infrahub.tasks")

    async def generate(self, data: dict) -> None:
        data: PodGeneratorQuery = PodGeneratorQuery(**data)

        self.pod_id: str = data.network_pod.edges[0].node.id
        self.pod_index: int = data.network_pod.edges[0].node.index.value
        self.pod_name: str = data.network_pod.edges[0].node.name.value.lower()
        self.pod_role: str = data.network_pod.edges[0].node.role.value
        self.pod_spine_switch_template = data.network_pod.edges[0].node.spine_switch_template.node.id
        self.fabric_id: str = data.network_pod.edges[0].node.parent.node.id
        self.fabric_name: str = data.network_pod.edges[0].node.parent.node.name.value.lower()
        self.amount_of_spines: int = data.network_pod.edges[0].node.amount_of_spines.value
        self.fabric_amount_of_super_spines: int = data.network_pod.edges[
            0
        ].node.parent.node.amount_of_super_spines.value

        self.spine_switches = []

        if self.pod_role in EXCLUDED_POD_ROLES:
            msg = f"Cannot run pod generator on {self.pod_name}-{self.pod_id}: {self.pod_role} is not supported by the generator!"
            raise ValueError(msg)

        await self.get_super_spine_switches_for_fabric()

        if self.fabric_amount_of_super_spines != len(self.super_spine_switches):
            msg = f"Cannot start pod generator on {self.pod_name}-{self.pod_id}: the fabric doesn't seem to be fully generated yet!"
            raise RuntimeError(msg)

        fabric_interface_sorting_method: str = data.network_pod.edges[
            0
        ].node.parent.node.fabric_interface_sorting_method.value
        spine_interface_sorting_method: str = data.network_pod.edges[
            0
        ].node.parent.node.spine_interface_sorting_method.value

        self.fabric_interface_sorting_function = getattr(solution_ai_dc_sorting, fabric_interface_sorting_method)
        self.spine_interface_sorting_function = getattr(solution_ai_dc_sorting, spine_interface_sorting_method)

        await self.allocate_resource_pools()

        await self.create_spine_switches()

        await self.connect_spine_to_super_spine()

        await self.update_checksum()

    async def create_spine_switches(self) -> None:
        """Create the spine switches"""

        for idx in range(1, self.amount_of_spines + 1):
            device = await self.client.create(
                NetworkDevice,
                hostname=f"spine-{self.pod_name}-{idx}",
                object_template={"id": self.pod_spine_switch_template},
                pod={"id": self.pod_id},
                loopback_ip=self.loopback_pool,
                role="spine",
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

            self.spine_switches.append(device)

    async def allocate_resource_pools(self) -> None:
        """Allocate IP Space for the Pod"""

        fabric_prefix_pool = await self.client.get(CoreIPPrefixPool, name__value=f"{self.fabric_name}-prefix-pool")

        pod_supernet = await self.client.allocate_next_ip_prefix(
            resource_pool=fabric_prefix_pool,
            identifier=self.pod_id,
            member_type="prefix",
            prefix_length=19,
            data={"role": "pod_supernet"},
        )

        self.pod_prefix_pool = await self.client.create(
            kind=CoreIPPrefixPool,
            name=f"{self.fabric_name}-{self.pod_name}-prefix-pool",
            default_prefix_type="IpamIPPrefix",
            default_prefix_length=24,
            ip_namespace={"hfid": ["default"]},
            resources=[pod_supernet],
        )
        await self.pod_prefix_pool.save(allow_upsert=True)

        pod_loopback_prefix = await self.client.allocate_next_ip_prefix(
            resource_pool=self.pod_prefix_pool,
            identifier=str(self.pod_id),
            member_type="address",
            prefix_length=27,
            data={"role": "pod_loopback"},
        )

        self.loopback_pool = await self.client.create(
            kind=CoreIPAddressPool,
            name=f"{self.fabric_name}-{self.pod_name}-loopback-pool",
            default_address_type="IpamIPAddress",
            default_prefix_length=32,
            ip_namespace={"hfid": ["default"]},
            resources=[pod_loopback_prefix],
        )
        await self.loopback_pool.save(allow_upsert=True)

        pod = await self.client.get(kind=NetworkPod, id=self.pod_id)
        pod.loopback_pool = self.loopback_pool
        pod.prefix_pool = self.pod_prefix_pool
        await pod.save(allow_upsert=True)

    async def get_super_spine_switches_for_fabric(self) -> tuple[NetworkPod, list[NetworkDevice]]:
        self.fabric_pod = await self.client.get(kind=NetworkPod, parent__ids=[self.fabric_id], role__value="fabric")
        self.super_spine_switches = await self.client.filters(
            kind=NetworkDevice, pod__ids=[self.fabric_pod.id], role__value="super_spine"
        )
        return self.fabric_pod, self.super_spine_switches

    async def connect_spine_to_super_spine(self) -> None:
        spine_interfaces = await self.client.filters(
            kind=NetworkInterface, device__ids=[spine.id for spine in self.spine_switches], role__value="super_spine"
        )
        spine_interface_map = self.spine_interface_sorting_function(spine_interfaces)

        super_spine_interfaces = await self.client.filters(
            kind=NetworkInterface, device__ids=[ss.id for ss in self.super_spine_switches], role__value="spine"
        )
        super_spine_interface_map = self.fabric_interface_sorting_function(super_spine_interfaces)

        created_cabling_plan: list[tuple[NetworkInterface, NetworkInterface]] = build_pod_cabling_plan(
            pod_index=self.pod_index,
            src_interface_map=spine_interface_map,
            dst_interface_map=super_spine_interface_map,
        )

        await connect_interface_maps(client=self.client, logger=self.logger, cabling_plan=created_cabling_plan)

        await assign_ip_addresses_to_p2p_connections(
            client=self.client,
            logger=self.logger,
            connections=created_cabling_plan,
            prefix_len=31,
            prefix_role="pod_super_spine_spine",
            pool=self.pod_prefix_pool,
        )

    async def update_checksum(self) -> None:
        racks = await self.client.filters(kind=LocationRack, pod__ids=[self.pod_id])

        # store the checksum for the fabric in the object itself
        checksum = self.calculate_checksum()
        for rack in racks:
            if rack.checksum.value != checksum:
                rack.checksum.value = checksum
                await rack.save(allow_upsert=True)
                self.logger.info(f"Rack {rack.name.value} has been updated to checksum {checksum}")
