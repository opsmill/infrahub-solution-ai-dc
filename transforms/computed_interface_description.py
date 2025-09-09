from infrahub_sdk.transforms import InfrahubTransform


class ComputedInterfaceDescription(InfrahubTransform):
    query = "computed_interface_description"

    async def transform(self, data):
        src_interface: str = data["NetworkInterface"]["edges"][0]["node"]["id"]
        network_link: dict = data["NetworkLink"]["edges"][0]["node"]
        endpoint_edges = network_link["endpoints"]["edges"]

        for endpoint_node in endpoint_edges:
            if endpoint_node["node"]["id"] == src_interface:
                continue
            dst_interface = endpoint_node["node"]
            return f"-> {dst_interface['device']['node']['hostname']['value']} {dst_interface['name']['value']}"

        return ""
