from typing import Any

from infrahub_sdk.transforms import InfrahubTransform

from solution_ai_dc.protocols import LocationRack, NetworkDevice, NetworkLink, NetworkInterface, NetworkPod

class CablingPlan(InfrahubTransform):
    query = "cabling_plan"

    async def transform(self, data: dict[str, Any]) -> str:
        link_ids = []
        pod_ids = []
        device_ids = []
        rack_ids = []
        interface_ids = []
        pod_nodes = data["NetworkFabric"]["edges"][0]["node"]["children"]["edges"]
        csv_data = []

        for pod_node in pod_nodes:
            pod = pod_node["node"]
            pod_ids.append(pod["id"])
            for device_node in pod["devices"]["edges"]:
                device = device_node["node"]
                device_ids.append(device["id"])

                if device["rack"]["node"]:
                    rack_ids.append(device["rack"]["node"]["id"])

                for interface_node in device["interfaces"]["edges"]:
                    interface = interface_node["node"]
                    interface_ids.append(interface["id"])
                    if interface["link"]["node"] != None:
                        link_ids.append(interface["link"]["node"]["id"])

        pods = await self.client.filters(NetworkPod, ids=pod_ids, include=["devices"])
        devices = await self.client.filters(NetworkDevice, ids=device_ids, include=["interfaces", "rack"])
        interfaces = await self.client.filters(NetworkInterface, ids=interface_ids, include=["link"])
        links = await self.client.filters(NetworkLink, ids=link_ids, include=["endpoints"])
        racks = await self.client.filters(LocationRack, ids=rack_ids, include=["devices"])

        header = ",".join(["Pod", "Source Rack", "Source Device", "Source Interface", "Destination Rack", "Destination Device", "Destination Interface"])
        for link in links:
            [src_interface, dst_interface] = link.endpoints.peers

            csv_data.append(
                [
                    src_interface.peer.device.peer.pod.peer.name.value,
                    src_interface.peer.device.peer.rack.peer.name.value if src_interface.peer.device.peer.rack.initialized else "",
                    src_interface.peer.device.peer.hostname.value,
                    src_interface.peer.name.value,
                    dst_interface.peer.device.peer.rack.peer.name.value if dst_interface.peer.device.peer.rack.initialized else "",
                    dst_interface.peer.device.peer.hostname.value,
                    dst_interface.peer.name.value
                 ]
            )

        rows = "\n".join([",".join(entry) for entry in csv_data])
        return header + "\n" + rows
