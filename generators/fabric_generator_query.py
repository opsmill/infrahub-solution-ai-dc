from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class FabricGeneratorQuery(BaseModel):
    network_fabric: FabricGeneratorQueryNetworkFabric = Field(alias="NetworkFabric")


class FabricGeneratorQueryNetworkFabric(BaseModel):
    edges: list[FabricGeneratorQueryNetworkFabricEdges]


class FabricGeneratorQueryNetworkFabricEdges(BaseModel):
    node: FabricGeneratorQueryNetworkFabricEdgesNode | None


class FabricGeneratorQueryNetworkFabricEdgesNode(BaseModel):
    id: str
    name: FabricGeneratorQueryNetworkFabricEdgesNodeName | None
    amount_of_super_spines: FabricGeneratorQueryNetworkFabricEdgesNodeAmountOfSuperSpines | None
    super_spine_switch_template: FabricGeneratorQueryNetworkFabricEdgesNodeSuperSpineSwitchTemplate


class FabricGeneratorQueryNetworkFabricEdgesNodeName(BaseModel):
    value: str | None


class FabricGeneratorQueryNetworkFabricEdgesNodeAmountOfSuperSpines(BaseModel):
    value: Any | None


class FabricGeneratorQueryNetworkFabricEdgesNodeSuperSpineSwitchTemplate(BaseModel):
    node: FabricGeneratorQueryNetworkFabricEdgesNodeSuperSpineSwitchTemplateNode | None


class FabricGeneratorQueryNetworkFabricEdgesNodeSuperSpineSwitchTemplateNode(BaseModel):
    typename__: Literal["CoreObjectTemplate", "TemplateNetworkDevice"] = Field(alias="__typename")
    id: str | None


FabricGeneratorQuery.model_rebuild()
FabricGeneratorQueryNetworkFabric.model_rebuild()
FabricGeneratorQueryNetworkFabricEdges.model_rebuild()
FabricGeneratorQueryNetworkFabricEdgesNode.model_rebuild()
FabricGeneratorQueryNetworkFabricEdgesNodeSuperSpineSwitchTemplate.model_rebuild()
