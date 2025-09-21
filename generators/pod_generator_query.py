from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field


class PodGeneratorQuery(BaseModel):
    network_pod: PodGeneratorQueryNetworkPod = Field(alias="NetworkPod")


class PodGeneratorQueryNetworkPod(BaseModel):
    edges: list[PodGeneratorQueryNetworkPodEdges]


class PodGeneratorQueryNetworkPodEdges(BaseModel):
    node: PodGeneratorQueryNetworkPodEdgesNode | None


class PodGeneratorQueryNetworkPodEdgesNode(BaseModel):
    id: str
    amount_of_spines: PodGeneratorQueryNetworkPodEdgesNodeAmountOfSpines | None
    name: PodGeneratorQueryNetworkPodEdgesNodeName | None
    checksum: PodGeneratorQueryNetworkPodEdgesNodeChecksum | None
    index: PodGeneratorQueryNetworkPodEdgesNodeIndex | None
    role: PodGeneratorQueryNetworkPodEdgesNodeRole | None
    spine_switch_template: PodGeneratorQueryNetworkPodEdgesNodeSpineSwitchTemplate
    parent: PodGeneratorQueryNetworkPodEdgesNodeParent


class PodGeneratorQueryNetworkPodEdgesNodeAmountOfSpines(BaseModel):
    value: Any | None


class PodGeneratorQueryNetworkPodEdgesNodeName(BaseModel):
    value: str | None


class PodGeneratorQueryNetworkPodEdgesNodeChecksum(BaseModel):
    value: str | None


class PodGeneratorQueryNetworkPodEdgesNodeIndex(BaseModel):
    value: Any | None


class PodGeneratorQueryNetworkPodEdgesNodeRole(BaseModel):
    value: str | None


class PodGeneratorQueryNetworkPodEdgesNodeSpineSwitchTemplate(BaseModel):
    node: PodGeneratorQueryNetworkPodEdgesNodeSpineSwitchTemplateNode | None


class PodGeneratorQueryNetworkPodEdgesNodeSpineSwitchTemplateNode(BaseModel):
    typename__: Literal["CoreObjectTemplate", "TemplateNetworkDevice"] = Field(alias="__typename")
    id: str | None


class PodGeneratorQueryNetworkPodEdgesNodeParent(BaseModel):
    node: (
        Annotated[
            PodGeneratorQueryNetworkPodEdgesNodeParentNodeNetworkBuildingBlock
            | PodGeneratorQueryNetworkPodEdgesNodeParentNodeNetworkFabric,
            Field(discriminator="typename__"),
        ]
        | None
    )


class PodGeneratorQueryNetworkPodEdgesNodeParentNodeNetworkBuildingBlock(BaseModel):
    typename__: Literal["NetworkBuildingBlock", "NetworkPod"] = Field(alias="__typename")
    id: str | None
    name: PodGeneratorQueryNetworkPodEdgesNodeParentNodeNetworkBuildingBlockName | None


class PodGeneratorQueryNetworkPodEdgesNodeParentNodeNetworkBuildingBlockName(BaseModel):
    value: str | None


class PodGeneratorQueryNetworkPodEdgesNodeParentNodeNetworkFabric(BaseModel):
    typename__: Literal["NetworkFabric"] = Field(alias="__typename")
    id: str
    name: PodGeneratorQueryNetworkPodEdgesNodeParentNodeNetworkFabricName | None
    amount_of_super_spines: PodGeneratorQueryNetworkPodEdgesNodeParentNodeNetworkFabricAmountOfSuperSpines | None
    fabric_interface_sorting_method: (
        PodGeneratorQueryNetworkPodEdgesNodeParentNodeNetworkFabricFabricInterfaceSortingMethod | None
    )
    spine_interface_sorting_method: (
        PodGeneratorQueryNetworkPodEdgesNodeParentNodeNetworkFabricSpineInterfaceSortingMethod | None
    )


class PodGeneratorQueryNetworkPodEdgesNodeParentNodeNetworkFabricName(BaseModel):
    value: str | None


class PodGeneratorQueryNetworkPodEdgesNodeParentNodeNetworkFabricAmountOfSuperSpines(BaseModel):
    value: Any | None


class PodGeneratorQueryNetworkPodEdgesNodeParentNodeNetworkFabricFabricInterfaceSortingMethod(BaseModel):
    value: str | None


class PodGeneratorQueryNetworkPodEdgesNodeParentNodeNetworkFabricSpineInterfaceSortingMethod(BaseModel):
    value: str | None


PodGeneratorQuery.model_rebuild()
PodGeneratorQueryNetworkPod.model_rebuild()
PodGeneratorQueryNetworkPodEdges.model_rebuild()
PodGeneratorQueryNetworkPodEdgesNode.model_rebuild()
PodGeneratorQueryNetworkPodEdgesNodeSpineSwitchTemplate.model_rebuild()
PodGeneratorQueryNetworkPodEdgesNodeParent.model_rebuild()
PodGeneratorQueryNetworkPodEdgesNodeParentNodeNetworkBuildingBlock.model_rebuild()
PodGeneratorQueryNetworkPodEdgesNodeParentNodeNetworkFabric.model_rebuild()
