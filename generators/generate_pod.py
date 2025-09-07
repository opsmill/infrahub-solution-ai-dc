from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from infrahub_sdk.generator import InfrahubGenerator
from infrahub_sdk.node import InfrahubNode
from infrahub_sdk.protocols import CoreIPAddressPool, CoreIPPrefixPool

from solution_ai_dc.addressing import assign_ip_addresses_to_p2p_connections
from solution_ai_dc.cabling import build_cabling_plan, connect_interface_maps
from solution_ai_dc.generator import GeneratorMixin
from solution_ai_dc.protocols import LocationRack, LocationRackBuilder, NetworkDevice, NetworkInterface, NetworkPod
from solution_ai_dc.sorting import create_sorted_device_interface_map

if TYPE_CHECKING:
    from infrahub_sdk.node import InfrahubNode


class PodGenerator(InfrahubGenerator, GeneratorMixin):
    pod_id: str
    pod_index: int
    pod_name: str

    fabric_id: str
    fabric_name: str

    loopback_pool: CoreIPAddressPool

    pod_prefix_pool: CoreIPPrefixPool
    spine_switches: list[NetworkDevice]

    logger = logging.getLogger("infrahub.tasks")

    async def generate(self, data: dict) -> None:
        self.pod_id: str = data["NetworkPodBuilder"]["edges"][0]["node"]["target"]["node"]["id"]
        self.pod_index: int = data["NetworkPodBuilder"]["edges"][0]["node"]["target"]["node"]["index"]["value"]
        self.pod_name: str = data["NetworkPodBuilder"]["edges"][0]["node"]["target"]["node"]["name"]["value"].lower()
        self.fabric_id: str = data["NetworkPodBuilder"]["edges"][0]["node"]["target"]["node"]["parent"]["node"]["id"]
        self.fabric_name: str = data["NetworkPodBuilder"]["edges"][0]["node"]["target"]["node"]["parent"]["node"][
            "name"
        ]["value"].lower()
        self.spine_switches = []

        await self.allocate_resource_pools()

        await self.create_spine_switches()

        await self.connect_spine_to_super_spine()

        await self.update_checksum()

    async def create_spine_switches(self) -> None:
        """Create the spine switches"""

        for idx in range(1, 5):
            device = await self.client.create(
                NetworkDevice,
                hostname=f"spine-{self.pod_name}-{idx}",
                object_template={"hfid": ["Spine Switch"]},
                pod={"id": self.pod_id},
                loopback_ip=self.loopback_pool,
                role="spine",
            )
            await device.save(allow_upsert=True)
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

    async def connect_spine_to_super_spine(self) -> None:
        fabric_pod = await self.client.get(kind=NetworkPod, parent__ids=[self.fabric_id], role__value="fabric")
        super_spine_switches = await self.client.filters(
            kind=NetworkDevice, pod__ids=[fabric_pod.id], role__value="super_spine"
        )

        spine_interfaces = await self.client.filters(
            kind=NetworkInterface, device__ids=[spine.id for spine in self.spine_switches], role__value="super_spine"
        )
        spine_interface_map = create_sorted_device_interface_map(spine_interfaces)

        super_spine_interfaces = await self.client.filters(
            kind=NetworkInterface, device__ids=[ss.id for ss in super_spine_switches], role__value="spine"
        )
        super_spine_interface_map = create_sorted_device_interface_map(super_spine_interfaces)

        created_cabling_plan: list[tuple[InfrahubNode, InfrahubNode]] = build_cabling_plan(
            logger=self.logger,
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
        rack_trackers = await self.client.filters(kind=LocationRackBuilder, target__ids=[rack.id for rack in racks])

        # store the checksum for the fabric in the object itself
        checksum = self.calculate_checksum()
        for rack_tracker in rack_trackers:
            if rack_tracker.checksum.value != checksum:
                rack_tracker.checksum.value = checksum
                await rack_tracker.save(allow_upsert=True)
                self.logger.info(f"Rack Tracker {rack_tracker.name.value} has been updated to checksum {checksum}")
