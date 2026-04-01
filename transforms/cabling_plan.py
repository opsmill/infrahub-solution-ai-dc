from typing import Any, NamedTuple

from infrahub_sdk.transforms import InfrahubTransform

from infrahub_solution_ai_dc.protocols import LocationRack, NetworkDevice, NetworkInterface, NetworkLink

from .fabric_cabling_plan_query import FabricCablingPlanQuery


class ProcessedInputData(NamedTuple):
    link_ids: list[str]
    pod_ids: list[str]
    device_ids: list[str]
    rack_ids: list[str]
    interface_ids: list[str]


class CablingPlan(InfrahubTransform):
    query = "cabling_plan"

    def generate_csv(self, links: list[NetworkLink]) -> str:
        csv_data: list[list[str]] = []

        header: str = ",".join(  # noqa: FLY002
            [
                "Source Rack",
                "Source Device",
                "Source Interface",
                "Destination Rack",
                "Destination Device",
                "Destination Interface",
            ]
        )
        for link in links:
            [src_interface, dst_interface] = link.endpoints.peers

            csv_data.append(
                [
                    src_interface.peer.device.peer.rack.peer.name.value
                    if src_interface.peer.device.peer.rack.initialized
                    else "",
                    src_interface.peer.device.peer.hostname.value,
                    src_interface.peer.name.value,
                    dst_interface.peer.device.peer.rack.peer.name.value
                    if dst_interface.peer.device.peer.rack.initialized
                    else "",
                    dst_interface.peer.device.peer.hostname.value,
                    dst_interface.peer.name.value,
                ]
            )

        rows = "\n".join([",".join(entry) for entry in csv_data])
        return header + "\n" + rows

    def process_transform_input_data(self, data: FabricCablingPlanQuery) -> ProcessedInputData:
        link_ids: list[str] = []
        pod_ids: list[str] = []
        device_ids: list[str] = []
        rack_ids: list[str] = []
        interface_ids: list[str] = []
        pod_nodes = data.network_fabric.edges[0].node.children.edges  # type: ignore[union-attr]

        for pod_node in pod_nodes:  # type: ignore[union-attr]
            pod = pod_node.node
            pod_ids.append(pod.id)  # type: ignore[union-attr, arg-type]
            for device_node in pod.devices.edges:  # type: ignore[union-attr]
                device = device_node.node
                device_ids.append(device.id)  # type: ignore[union-attr]

                if device.rack.node:  # type: ignore[union-attr]
                    rack_ids.append(device.rack.node.id)  # type: ignore[union-attr]

                for interface_node in device.interfaces.edges:  # type: ignore[union-attr]
                    interface = interface_node.node
                    interface_ids.append(interface.id)  # type: ignore[union-attr]
                    if interface.link.node is not None:  # type: ignore[union-attr]
                        link_ids.append(interface.link.node.id)  # type: ignore[union-attr]

        return ProcessedInputData(link_ids, pod_ids, device_ids, rack_ids, interface_ids)

    async def transform(self, data: dict[str, Any]) -> str:
        parsed = FabricCablingPlanQuery(**data)
        link_ids, _pod_ids, device_ids, rack_ids, interface_ids = self.process_transform_input_data(data=parsed)

        links: list[NetworkLink] = await self.client.filters(NetworkLink, ids=link_ids, include=["endpoints"])

        # populate SDK client store with all relevant objects
        await self.client.filters(NetworkDevice, ids=device_ids, include=["interfaces", "rack"])
        await self.client.filters(NetworkInterface, ids=interface_ids, include=["link", "device"])
        await self.client.filters(LocationRack, ids=rack_ids, include=["devices"])

        return self.generate_csv(links)
