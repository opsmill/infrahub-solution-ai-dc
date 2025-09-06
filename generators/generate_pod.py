from __future__ import annotations

import logging
from collections import defaultdict
from ipaddress import IPv4Address

from netutils.interface import sort_interface_list

from infrahub_sdk import InfrahubClient
from infrahub_sdk.generator import InfrahubGenerator
from infrahub_sdk.node import InfrahubNode
from infrahub_sdk.protocols import CoreIPAddressPool, CoreIPPrefixPool


def create_sorted_device_interface_map(interfaces: list[InfrahubNode]) -> dict[str, list[InfrahubNode]]:
    """
    Creates a dictionary that maps a device hostname to a sorted list of interfaces from a list of interfaces
    """

    device_interface_map = defaultdict(list)

    for interface in interfaces:
        device_interface_map[interface.device.display_label].append(interface)

    for device, interfaces in device_interface_map.items():
        interface_map = {interface.name.value: interface for interface in interfaces}
        sorted_interface_names = sort_interface_list(list(interface_map.keys()))
        device_interface_map[device] = [interface_map[interface] for interface in sorted_interface_names]

    return device_interface_map


def build_cabling_plan(
    logger,
    pod_index: int,
    src_interface_map: dict[str, list[InfrahubNode]],
    dst_interface_map: dict[str, list[InfrahubNode]],
) -> list[tuple[InfrahubNode, InfrahubNode]]:
    """Builds a cabling plan between source and destination interfaces based in Indexes

    TODO Write unit test to validate that the algorithm works as expected
    """
    dst_device_names = list(dst_interface_map.keys())
    dst_device_count = len(dst_device_names)
    dst_interface_base_index = (pod_index - 2) * len(dst_interface_map)
    src_index = 0

    cabling_plan: list[tuple[InfrahubNode, InfrahubNode]] = []

    for src_device, src_interfaces in src_interface_map.items():
        dst_interface_index = dst_interface_base_index + src_index

        for dst_index, src_interface in enumerate(src_interfaces[:dst_device_count]):
            dst_interface = dst_interface_map[dst_device_names[dst_index]][dst_interface_index]

            cabling_plan.append((src_interface, dst_interface))

        src_index += 1
        dst_interface_index = dst_interface_base_index + src_index

    return cabling_plan


async def connect_interface_maps(
    client: InfrahubClient, logger: logging.Logger, cabling_plan: list[tuple[InfrahubNode, InfrahubNode]]
):
    for src_interface, dst_interface in cabling_plan:
        name = f"{src_interface.device.display_label}-{src_interface.name.value}__{dst_interface.device.display_label}-{dst_interface.name.value}"
        network_link = await client.create(
            kind="NetworkLink", name=name, medium="copper", endpoints=[src_interface, dst_interface]
        )
        await network_link.save(allow_upsert=True)
        logger.info(f"Connected {name}")


async def assign_ip_address_to_interface(
    client: InfrahubClient,
    interface: InfrahubNode,
    logger: logging.Logger,
    host_addresses: Generator[IPv4Address],
    prefix_len: int
):
    ip_address = await client.create(kind="IpamIPAddress", address=str(next(host_addresses)) + f"/{prefix_len}")
    await ip_address.save(allow_upsert=True)
    interface.ip_address = ip_address
    await interface.save(allow_upsert=True)
    logger.info(f"Assigned {ip_address.address.value} to {interface.display_label}")

async def assign_ip_addresses_to_p2p_connections(
    client: InfrahubClient, logger: logging.Logger, connections: list[tuple[InfrahubNode, InfrahubNode]], prefix_len: int, prefix_role: str, pool: CoreIPPrefixPool
):
        for src_interface, dst_interface in connections:

            # allocate a new prefix for the p2p connection
            prefix = await client.allocate_next_ip_prefix(
                resource_pool=pool,
                identifier=src_interface.id + dst_interface.id,
                member_type="address",
                prefix_length=prefix_len,
                data={"role": prefix_role},
            )

            logger.info(f"Allocated prefix {prefix.prefix.value} for connection between {src_interface.display_label}-{dst_interface.display_label}")

            host_addresses = prefix.prefix.value.hosts()

            for interface in [src_interface, dst_interface]:
                await assign_ip_address_to_interface(client, interface, logger, host_addresses, prefix_len)


class PodGenerator(InfrahubGenerator):
    pod_id: str
    pod_index: int
    pod_name: str

    fabric_id: str
    fabric_name: str

    loopback_pool: CoreIPAddressPool

    pod_prefix_pool: CoreIPPrefixPool

    logger = logging.getLogger("infrahub.tasks")

    async def generate(self, data: dict) -> None:
        self.pod_id: str = data["NetworkPodBuilder"]["edges"][0]["node"]["building_block"]["node"]["id"]
        self.pod_index: int = data["NetworkPodBuilder"]["edges"][0]["node"]["building_block"]["node"]["index"]["value"]
        self.pod_name: str = data["NetworkPodBuilder"]["edges"][0]["node"]["building_block"]["node"]["name"]["value"].lower()
        self.fabric_id: str = data["NetworkPodBuilder"]["edges"][0]["node"]["building_block"]["node"]["parent"]["node"]["id"]
        self.fabric_name: str = data["NetworkPodBuilder"]["edges"][0]["node"]["building_block"]["node"]["parent"]["node"]["name"]["value"].lower()

        await self.allocate_resource_pools()

        # Create the spine switches
        spine_switches = []
        for idx in range(1, 5):
            device = await self.client.create(
                "NetworkDevice",
                hostname=f"spine-{self.pod_name}-{idx}",
                object_template={"hfid": ["Spine Switch"]},
                pod={"id": self.pod_id},
                loopback_ip=self.loopback_pool,
                role="spine",
            )
            await device.save(allow_upsert=True)
            spine_switches.append(device)

        # Connect the Spine to the SuperSpine
        fabric_pod = await self.client.get(kind="NetworkPod", parent__ids=[self.fabric_id], role__value="fabric")
        super_spine_switches = await self.client.filters(
            kind="NetworkDevice", pod__ids=[fabric_pod.id], role__value="super_spine"
        )

        spine_interfaces = await self.client.filters(
            kind="NetworkInterface", device__ids=[spine.id for spine in spine_switches], role__value="super_spine"
        )
        spine_interface_map = create_sorted_device_interface_map(spine_interfaces)

        super_spine_interfaces = await self.client.filters(
            kind="NetworkInterface", device__ids=[ss.id for ss in super_spine_switches], role__value="spine"
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
