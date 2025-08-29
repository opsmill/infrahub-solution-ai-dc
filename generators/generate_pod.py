from __future__ import annotations

import logging

from collections import defaultdict
from typing import Dict, List

from infrahub_sdk import InfrahubClient
from infrahub_sdk.generator import InfrahubGenerator
from infrahub_sdk.node import InfrahubNode
from netutils.interface import sort_interface_list

def create_sorted_device_interface_map(interfaces: List[InfrahubNode]) -> Dict[str, List[InfrahubNode]]:
    """
    Creates a dictionary that maps a device hostname to a sorted list of interfaces from a list of interfaces
    """

    device_interface_map = defaultdict(list)

    for interface in interfaces:
        device_interface_map[interface.device.display_label].append(interface)

    for device, interfaces in device_interface_map.items():
        interface_map = {
            interface.name.value: interface
            for interface in interfaces
        }
        sorted_interface_names = sort_interface_list(list(interface_map.keys()))
        device_interface_map[device] = [
            interface_map[interface]
            for interface in sorted_interface_names
        ]

    return device_interface_map

async def connect_interface_maps(
    client: InfrahubClient,
    logger: logging.Logger,
    pod_index: int,
    src_interface_map: Dict[str, InfrahubNode],
    dst_interface_map: Dict[str, InfrahubNode]
):
    """
    """

    dst_device_names = list(dst_interface_map.keys())
    dst_device_count = len(dst_device_names)
    dst_interface_base_index = (pod_index - 2) * len(dst_interface_map)
    src_index = 0

    for src_device, src_interfaces in src_interface_map.items():
        dst_interface_index = dst_interface_base_index + src_index

        for dst_index, src_interface in enumerate(src_interfaces[:dst_device_count]):

            dst_interface = dst_interface_map[dst_device_names[dst_index]][dst_interface_index]
            name=f"{src_interface.device.display_label}-{src_interface.name.value}__{dst_interface.device.display_label}-{dst_interface.name.value}"
            network_link = await client.create(
                kind="NetworkLink",
                name=name,
                medium="copper",
                endpoints = [src_interface, dst_interface]
            )
            await network_link.save(allow_upsert=True)
            logger.info(f"Connected {name}")

        src_index += 1
        dst_interface_index = dst_interface_base_index + src_index

class PodGenerator(InfrahubGenerator):

    logger = logging.getLogger("infrahub.tasks")

    async def generate(self, data: dict) -> None:

        pod_id: str = data["NetworkPod"]["edges"][0]["node"]["id"]
        pod_index: int = data["NetworkPod"]["edges"][0]["node"]["index"]["value"]
        pod_name: str = data["NetworkPod"]["edges"][0]["node"]["name"]["value"].lower()
        fabric_id: str = data["NetworkPod"]["edges"][0]["node"]["parent"]["node"]["id"]
        fabric_name: str = data["NetworkPod"]["edges"][0]["node"]["parent"]["node"]["name"]["value"].lower()

        fabric_prefix_pool = await self.client.get("CoreIPPrefixPool", name__value=f"{fabric_name}-prefix-pool")

        # allocate ip space for the pod
        pod_supernet = await self.client.allocate_next_ip_prefix(
            resource_pool = fabric_prefix_pool,
            identifier=pod_id,
            member_type="prefix",
            prefix_length=19,
            data = {
                "role": "pod_supernet"
            }
        )

        pod_prefix_pool = await self.client.create(
            kind="CoreIPPrefixPool",
            name=f"{fabric_name}-{pod_name}-prefix-pool",
            default_prefix_type = "IpamIPPrefix",
            default_prefix_length = 24,
            ip_namespace = {"hfid": ["default"]},
            resources = [pod_supernet]
        )

        await pod_prefix_pool.save(allow_upsert=True)

        pod_loopback_prefix = await self.client.allocate_next_ip_prefix(
            resource_pool=pod_prefix_pool,
            identifier=pod_id,
            member_type="address",
            prefix_length=27,
            data={
                "role": "pod_loopback"
            }
        )

        pod_loopback_pool = await self.client.create(
            kind="CoreIPAddressPool",
            name=f"{fabric_name}-{pod_name}-loopback-pool",
            default_address_type = "IpamIPAddress",
            default_prefix_length = 32,
            ip_namespace = {"hfid": ["default"]},
            resources = [pod_loopback_prefix]
        )

        await pod_loopback_pool.save(allow_upsert=True)

        # Create the spine switches
        spine_switches = []
        for idx in range(1, 5):
            device = await self.client.create(
                "NetworkDevice",
                hostname=f"spine-{pod_name}-{idx}",
                object_template={ "hfid": ["Spine Switch"]},
                pod={"id": pod_id},
                loopback_ip=pod_loopback_pool,
                role="spine"
            )
            await device.save(allow_upsert=True)
            spine_switches.append(device)

        # Connect the Spine to the SuperSpine
        fabric_pod = await self.client.get(
            kind="NetworkPod",
            parent__ids=[fabric_id],
            role__value="fabric"
        )
        super_spine_switches = await self.client.filters(
            kind="NetworkDevice",
            pod__ids=[fabric_pod.id],
            role__value="super_spine"
        )

        spine_interfaces = await self.client.filters(
            kind="NetworkInterface",
            device__ids=[spine.id for spine in spine_switches],
            role__value="super_spine"
        )
        spine_interface_map = create_sorted_device_interface_map(spine_interfaces)

        super_spine_interfaces = await self.client.filters(
            kind="NetworkInterface",
            device__ids=[ss.id for ss in super_spine_switches],
            role__value="spine"
        )
        super_spine_interface_map = create_sorted_device_interface_map(super_spine_interfaces)

        await connect_interface_maps(
            client=self.client,
            logger=self.logger,
            pod_index=pod_index,
            src_interface_map=spine_interface_map,
            dst_interface_map=super_spine_interface_map
        )
