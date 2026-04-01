from typing import Any

from infrahub_sdk.transforms import InfrahubTransform

from .computed_interface_description_query import ComputedInterfaceDescriptionQuery


class ComputedInterfaceDescription(InfrahubTransform):
    query = "computed_interface_description"

    async def transform(self, data: dict[str, Any]) -> str:
        parsed = ComputedInterfaceDescriptionQuery(**data)
        node = parsed.network_interface.edges[0].node
        assert node is not None

        src_interface = node.id
        network_link = node.link.node  # type: ignore[union-attr]

        if not network_link:
            return ""

        endpoint_edges = network_link.endpoints.edges  # type: ignore[union-attr]

        for endpoint_node in endpoint_edges:  # type: ignore[union-attr]
            if endpoint_node.node.id == src_interface:  # type: ignore[union-attr]
                continue
            dst_interface = endpoint_node.node
            return f"-> {dst_interface.device.node.hostname.value} {dst_interface.name.value}"  # type: ignore[union-attr]

        return ""
