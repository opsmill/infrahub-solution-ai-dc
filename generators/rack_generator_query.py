from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class RackGeneratorQuery(BaseModel):
    location_rack: RackGeneratorQueryLocationRack = Field(alias="LocationRack")


class RackGeneratorQueryLocationRack(BaseModel):
    edges: list[RackGeneratorQueryLocationRackEdges]


class RackGeneratorQueryLocationRackEdges(BaseModel):
    node: RackGeneratorQueryLocationRackEdgesNode | None


class RackGeneratorQueryLocationRackEdgesNode(BaseModel):
    id: str
    name: RackGeneratorQueryLocationRackEdgesNodeName | None
    checksum: RackGeneratorQueryLocationRackEdgesNodeChecksum | None
    index: RackGeneratorQueryLocationRackEdgesNodeIndex | None
    rack_type: RackGeneratorQueryLocationRackEdgesNodeRackType | None
    amount_of_leafs: RackGeneratorQueryLocationRackEdgesNodeAmountOfLeafs | None
    leaf_switch_template: RackGeneratorQueryLocationRackEdgesNodeLeafSwitchTemplate
    parent: RackGeneratorQueryLocationRackEdgesNodeParent
    pod: RackGeneratorQueryLocationRackEdgesNodePod


class RackGeneratorQueryLocationRackEdgesNodeName(BaseModel):
    value: str | None


class RackGeneratorQueryLocationRackEdgesNodeChecksum(BaseModel):
    value: str | None


class RackGeneratorQueryLocationRackEdgesNodeIndex(BaseModel):
    value: Any | None


class RackGeneratorQueryLocationRackEdgesNodeRackType(BaseModel):
    value: str | None


class RackGeneratorQueryLocationRackEdgesNodeAmountOfLeafs(BaseModel):
    value: Any | None


class RackGeneratorQueryLocationRackEdgesNodeLeafSwitchTemplate(BaseModel):
    node: RackGeneratorQueryLocationRackEdgesNodeLeafSwitchTemplateNode | None


class RackGeneratorQueryLocationRackEdgesNodeLeafSwitchTemplateNode(BaseModel):
    typename__: Literal["CoreObjectTemplate", "TemplateNetworkDevice"] = Field(alias="__typename")
    id: str | None


class RackGeneratorQueryLocationRackEdgesNodeParent(BaseModel):
    node: RackGeneratorQueryLocationRackEdgesNodeParentNode | None


class RackGeneratorQueryLocationRackEdgesNodeParentNode(BaseModel):
    typename__: Literal["LocationHall", "LocationPhysical", "LocationRack"] = Field(alias="__typename")
    id: str | None
    name: RackGeneratorQueryLocationRackEdgesNodeParentNodeName | None


class RackGeneratorQueryLocationRackEdgesNodeParentNodeName(BaseModel):
    value: str | None


class RackGeneratorQueryLocationRackEdgesNodePod(BaseModel):
    node: RackGeneratorQueryLocationRackEdgesNodePodNode | None


class RackGeneratorQueryLocationRackEdgesNodePodNode(BaseModel):
    id: str
    name: RackGeneratorQueryLocationRackEdgesNodePodNodeName | None
    index: RackGeneratorQueryLocationRackEdgesNodePodNodeIndex | None
    prefix_pool: RackGeneratorQueryLocationRackEdgesNodePodNodePrefixPool
    loopback_pool: RackGeneratorQueryLocationRackEdgesNodePodNodeLoopbackPool
    amount_of_spines: RackGeneratorQueryLocationRackEdgesNodePodNodeAmountOfSpines | None
    leaf_interface_sorting_method: RackGeneratorQueryLocationRackEdgesNodePodNodeLeafInterfaceSortingMethod | None
    spine_interface_sorting_method: RackGeneratorQueryLocationRackEdgesNodePodNodeSpineInterfaceSortingMethod | None


class RackGeneratorQueryLocationRackEdgesNodePodNodeName(BaseModel):
    value: str | None


class RackGeneratorQueryLocationRackEdgesNodePodNodeIndex(BaseModel):
    value: Any | None


class RackGeneratorQueryLocationRackEdgesNodePodNodePrefixPool(BaseModel):
    node: RackGeneratorQueryLocationRackEdgesNodePodNodePrefixPoolNode | None


class RackGeneratorQueryLocationRackEdgesNodePodNodePrefixPoolNode(BaseModel):
    id: str


class RackGeneratorQueryLocationRackEdgesNodePodNodeLoopbackPool(BaseModel):
    node: RackGeneratorQueryLocationRackEdgesNodePodNodeLoopbackPoolNode | None


class RackGeneratorQueryLocationRackEdgesNodePodNodeLoopbackPoolNode(BaseModel):
    id: str


class RackGeneratorQueryLocationRackEdgesNodePodNodeAmountOfSpines(BaseModel):
    value: Any | None


class RackGeneratorQueryLocationRackEdgesNodePodNodeLeafInterfaceSortingMethod(BaseModel):
    value: str | None


class RackGeneratorQueryLocationRackEdgesNodePodNodeSpineInterfaceSortingMethod(BaseModel):
    value: str | None


RackGeneratorQuery.model_rebuild()
RackGeneratorQueryLocationRack.model_rebuild()
RackGeneratorQueryLocationRackEdges.model_rebuild()
RackGeneratorQueryLocationRackEdgesNode.model_rebuild()
RackGeneratorQueryLocationRackEdgesNodeLeafSwitchTemplate.model_rebuild()
RackGeneratorQueryLocationRackEdgesNodeParent.model_rebuild()
RackGeneratorQueryLocationRackEdgesNodeParentNode.model_rebuild()
RackGeneratorQueryLocationRackEdgesNodePod.model_rebuild()
RackGeneratorQueryLocationRackEdgesNodePodNode.model_rebuild()
RackGeneratorQueryLocationRackEdgesNodePodNodePrefixPool.model_rebuild()
RackGeneratorQueryLocationRackEdgesNodePodNodeLoopbackPool.model_rebuild()
