from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field


class FabricCablingPlanQuery(BaseModel):
    network_fabric: FabricCablingPlanQueryNetworkFabric = Field(alias="NetworkFabric")


class FabricCablingPlanQueryNetworkFabric(BaseModel):
    edges: list[FabricCablingPlanQueryNetworkFabricEdges]


class FabricCablingPlanQueryNetworkFabricEdges(BaseModel):
    node: FabricCablingPlanQueryNetworkFabricEdgesNode | None


class FabricCablingPlanQueryNetworkFabricEdgesNode(BaseModel):
    children: FabricCablingPlanQueryNetworkFabricEdgesNodeChildren


class FabricCablingPlanQueryNetworkFabricEdgesNodeChildren(BaseModel):
    edges: list[FabricCablingPlanQueryNetworkFabricEdgesNodeChildrenEdges] | None


class FabricCablingPlanQueryNetworkFabricEdgesNodeChildrenEdges(BaseModel):
    node: (
        Annotated[
            FabricCablingPlanQueryNetworkFabricEdgesNodeChildrenEdgesNodeNetworkBuildingBlock
            | FabricCablingPlanQueryNetworkFabricEdgesNodeChildrenEdgesNodeNetworkPod,
            Field(discriminator="typename__"),
        ]
        | None
    )


class FabricCablingPlanQueryNetworkFabricEdgesNodeChildrenEdgesNodeNetworkBuildingBlock(BaseModel):
    typename__: Literal["NetworkBuildingBlock", "NetworkFabric"] = Field(alias="__typename")
    id: str | None


class FabricCablingPlanQueryNetworkFabricEdgesNodeChildrenEdgesNodeNetworkPod(BaseModel):
    typename__: Literal["NetworkPod"] = Field(alias="__typename")
    id: str
    devices: FabricCablingPlanQueryNetworkFabricEdgesNodeChildrenEdgesNodeNetworkPodDevices


class FabricCablingPlanQueryNetworkFabricEdgesNodeChildrenEdgesNodeNetworkPodDevices(BaseModel):
    edges: list[FabricCablingPlanQueryNetworkFabricEdgesNodeChildrenEdgesNodeNetworkPodDevicesEdges]


class FabricCablingPlanQueryNetworkFabricEdgesNodeChildrenEdgesNodeNetworkPodDevicesEdges(BaseModel):
    node: FabricCablingPlanQueryNetworkFabricEdgesNodeChildrenEdgesNodeNetworkPodDevicesEdgesNode | None


class FabricCablingPlanQueryNetworkFabricEdgesNodeChildrenEdgesNodeNetworkPodDevicesEdgesNode(BaseModel):
    id: str
    rack: FabricCablingPlanQueryNetworkFabricEdgesNodeChildrenEdgesNodeNetworkPodDevicesEdgesNodeRack
    interfaces: FabricCablingPlanQueryNetworkFabricEdgesNodeChildrenEdgesNodeNetworkPodDevicesEdgesNodeInterfaces


class FabricCablingPlanQueryNetworkFabricEdgesNodeChildrenEdgesNodeNetworkPodDevicesEdgesNodeRack(BaseModel):
    node: FabricCablingPlanQueryNetworkFabricEdgesNodeChildrenEdgesNodeNetworkPodDevicesEdgesNodeRackNode | None


class FabricCablingPlanQueryNetworkFabricEdgesNodeChildrenEdgesNodeNetworkPodDevicesEdgesNodeRackNode(BaseModel):
    id: str


class FabricCablingPlanQueryNetworkFabricEdgesNodeChildrenEdgesNodeNetworkPodDevicesEdgesNodeInterfaces(BaseModel):
    edges: list[FabricCablingPlanQueryNetworkFabricEdgesNodeChildrenEdgesNodeNetworkPodDevicesEdgesNodeInterfacesEdges]


class FabricCablingPlanQueryNetworkFabricEdgesNodeChildrenEdgesNodeNetworkPodDevicesEdgesNodeInterfacesEdges(BaseModel):
    node: (
        FabricCablingPlanQueryNetworkFabricEdgesNodeChildrenEdgesNodeNetworkPodDevicesEdgesNodeInterfacesEdgesNode
        | None
    )


class FabricCablingPlanQueryNetworkFabricEdgesNodeChildrenEdgesNodeNetworkPodDevicesEdgesNodeInterfacesEdgesNode(
    BaseModel
):
    id: str
    link: FabricCablingPlanQueryNetworkFabricEdgesNodeChildrenEdgesNodeNetworkPodDevicesEdgesNodeInterfacesEdgesNodeLink


class FabricCablingPlanQueryNetworkFabricEdgesNodeChildrenEdgesNodeNetworkPodDevicesEdgesNodeInterfacesEdgesNodeLink(
    BaseModel
):
    node: (
        FabricCablingPlanQueryNetworkFabricEdgesNodeChildrenEdgesNodeNetworkPodDevicesEdgesNodeInterfacesEdgesNodeLinkNode
        | None
    )


class FabricCablingPlanQueryNetworkFabricEdgesNodeChildrenEdgesNodeNetworkPodDevicesEdgesNodeInterfacesEdgesNodeLinkNode(
    BaseModel
):
    id: str


FabricCablingPlanQuery.model_rebuild()
FabricCablingPlanQueryNetworkFabric.model_rebuild()
FabricCablingPlanQueryNetworkFabricEdges.model_rebuild()
FabricCablingPlanQueryNetworkFabricEdgesNode.model_rebuild()
FabricCablingPlanQueryNetworkFabricEdgesNodeChildren.model_rebuild()
FabricCablingPlanQueryNetworkFabricEdgesNodeChildrenEdges.model_rebuild()
FabricCablingPlanQueryNetworkFabricEdgesNodeChildrenEdgesNodeNetworkPod.model_rebuild()
FabricCablingPlanQueryNetworkFabricEdgesNodeChildrenEdgesNodeNetworkPodDevices.model_rebuild()
FabricCablingPlanQueryNetworkFabricEdgesNodeChildrenEdgesNodeNetworkPodDevicesEdges.model_rebuild()
FabricCablingPlanQueryNetworkFabricEdgesNodeChildrenEdgesNodeNetworkPodDevicesEdgesNode.model_rebuild()
FabricCablingPlanQueryNetworkFabricEdgesNodeChildrenEdgesNodeNetworkPodDevicesEdgesNodeRack.model_rebuild()
FabricCablingPlanQueryNetworkFabricEdgesNodeChildrenEdgesNodeNetworkPodDevicesEdgesNodeInterfaces.model_rebuild()
FabricCablingPlanQueryNetworkFabricEdgesNodeChildrenEdgesNodeNetworkPodDevicesEdgesNodeInterfacesEdges.model_rebuild()
FabricCablingPlanQueryNetworkFabricEdgesNodeChildrenEdgesNodeNetworkPodDevicesEdgesNodeInterfacesEdgesNode.model_rebuild()
FabricCablingPlanQueryNetworkFabricEdgesNodeChildrenEdgesNodeNetworkPodDevicesEdgesNodeInterfacesEdgesNodeLink.model_rebuild()
