from __future__ import annotations

import logging

from collections import defaultdict

from infrahub_sdk.generator import InfrahubGenerator
from infrahub_sdk.node import InfrahubNode
from netutils.interface import sort_interface_list


class PodGenerator(InfrahubGenerator):

    log = logging.getLogger("infrahub.tasks")

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
        fabric_pod = await self.client.get(kind="NetworkPod", parent__ids=[fabric_id], role__value="fabric")
        super_spine_switches = await self.client.filters(kind="NetworkDevice", pod__ids=[fabric_pod.id], role__value="super_spine")

        super_spine_interfaces = defaultdict(list)
        for interface in await self.client.filters(kind="NetworkInterface", device__ids=[ss.id for ss in super_spine_switches], role__value="spine"):
            super_spine_interfaces[interface.device.display_label].append(interface)

        for super_spine, interfaces in super_spine_interfaces.items():
            interface_map = {
                interface.name.value: interface
                for interface in interfaces
            }
            sorted_interface_names = sort_interface_list(list(interface_map.keys()))
            super_spine_interfaces[super_spine] = [
                interface_map[interface]
                for interface in sorted_interface_names
            ]

        spine_interfaces = defaultdict(list)
        for interface in await self.client.filters(kind="NetworkInterface", device__ids=[spine.id for spine in spine_switches], role__value="super_spine"):
            spine_interfaces[interface.device.display_label].append(interface)

        for spine, interfaces in spine_interfaces.items():
            interface_map = {
                interface.name.value: interface
                for interface in interfaces
            }
            sorted_interface_names = sort_interface_list(list(interface_map.keys()))
            spine_interfaces[spine] = [
                interface_map[interface]
                for interface in sorted_interface_names
            ]

        super_spine_interface_base_index = (pod_index - 2) * len(super_spine_interfaces)
        spine_index = 0

        super_spine_names = list(super_spine_interfaces.keys())
        for spine, src_interfaces in spine_interfaces.items():
            super_spine_interface_index = super_spine_interface_base_index + spine_index

            for super_spine_index, src_interface in enumerate(src_interfaces[:len(super_spine_interfaces)]):

                dst_interface = super_spine_interfaces[super_spine_names[super_spine_index]][super_spine_interface_index]
                network_link = await self.client.create(
                    kind="NetworkLink",
                    name=f"{src_interface.device.display_label}-{src_interface.name.value}__{dst_interface.device.display_label}-{dst_interface.name.value}",
                    medium="copper",
                    endpoints = [src_interface, dst_interface]
                )
                await network_link.save(allow_upsert=True)
                print(f"Connect {src_interface.device.display_label} {src_interface.name.value} - {dst_interface.device.display_label} {dst_interface.name.value}")

            spine_index += 1
            super_spine_interface_index = super_spine_interface_base_index + spine_index
