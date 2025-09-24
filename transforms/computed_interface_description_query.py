from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field


class ComputedInterfaceDescriptionQuery(BaseModel):
    network_interface: ComputedInterfaceDescriptionQueryNetworkInterface = Field(alias="NetworkInterface")


class ComputedInterfaceDescriptionQueryNetworkInterface(BaseModel):
    edges: list[ComputedInterfaceDescriptionQueryNetworkInterfaceEdges]


class ComputedInterfaceDescriptionQueryNetworkInterfaceEdges(BaseModel):
    node: ComputedInterfaceDescriptionQueryNetworkInterfaceEdgesNode | None


class ComputedInterfaceDescriptionQueryNetworkInterfaceEdgesNode(BaseModel):
    id: str
    link: ComputedInterfaceDescriptionQueryNetworkInterfaceEdgesNodeLink


class ComputedInterfaceDescriptionQueryNetworkInterfaceEdgesNodeLink(BaseModel):
    node: ComputedInterfaceDescriptionQueryNetworkInterfaceEdgesNodeLinkNode | None


class ComputedInterfaceDescriptionQueryNetworkInterfaceEdgesNodeLinkNode(BaseModel):
    id: str
    endpoints: ComputedInterfaceDescriptionQueryNetworkInterfaceEdgesNodeLinkNodeEndpoints


class ComputedInterfaceDescriptionQueryNetworkInterfaceEdgesNodeLinkNodeEndpoints(BaseModel):
    edges: list[ComputedInterfaceDescriptionQueryNetworkInterfaceEdgesNodeLinkNodeEndpointsEdges] | None


class ComputedInterfaceDescriptionQueryNetworkInterfaceEdgesNodeLinkNodeEndpointsEdges(BaseModel):
    node: (
        Annotated[
            ComputedInterfaceDescriptionQueryNetworkInterfaceEdgesNodeLinkNodeEndpointsEdgesNodeNetworkEndpoint
            | ComputedInterfaceDescriptionQueryNetworkInterfaceEdgesNodeLinkNodeEndpointsEdgesNodeNetworkInterface,
            Field(discriminator="typename__"),
        ]
        | None
    )


class ComputedInterfaceDescriptionQueryNetworkInterfaceEdgesNodeLinkNodeEndpointsEdgesNodeNetworkEndpoint(BaseModel):
    typename__: Literal["NetworkEndpoint"] = Field(alias="__typename")
    id: str | None


class ComputedInterfaceDescriptionQueryNetworkInterfaceEdgesNodeLinkNodeEndpointsEdgesNodeNetworkInterface(BaseModel):
    typename__: Literal["NetworkInterface"] = Field(alias="__typename")
    id: str
    name: (
        ComputedInterfaceDescriptionQueryNetworkInterfaceEdgesNodeLinkNodeEndpointsEdgesNodeNetworkInterfaceName | None
    )
    device: ComputedInterfaceDescriptionQueryNetworkInterfaceEdgesNodeLinkNodeEndpointsEdgesNodeNetworkInterfaceDevice


class ComputedInterfaceDescriptionQueryNetworkInterfaceEdgesNodeLinkNodeEndpointsEdgesNodeNetworkInterfaceName(
    BaseModel
):
    value: str | None


class ComputedInterfaceDescriptionQueryNetworkInterfaceEdgesNodeLinkNodeEndpointsEdgesNodeNetworkInterfaceDevice(
    BaseModel
):
    node: (
        ComputedInterfaceDescriptionQueryNetworkInterfaceEdgesNodeLinkNodeEndpointsEdgesNodeNetworkInterfaceDeviceNode
        | None
    )


class ComputedInterfaceDescriptionQueryNetworkInterfaceEdgesNodeLinkNodeEndpointsEdgesNodeNetworkInterfaceDeviceNode(
    BaseModel
):
    hostname: (
        ComputedInterfaceDescriptionQueryNetworkInterfaceEdgesNodeLinkNodeEndpointsEdgesNodeNetworkInterfaceDeviceNodeHostname
        | None
    )


class ComputedInterfaceDescriptionQueryNetworkInterfaceEdgesNodeLinkNodeEndpointsEdgesNodeNetworkInterfaceDeviceNodeHostname(
    BaseModel
):
    value: str | None


ComputedInterfaceDescriptionQuery.model_rebuild()
ComputedInterfaceDescriptionQueryNetworkInterface.model_rebuild()
ComputedInterfaceDescriptionQueryNetworkInterfaceEdges.model_rebuild()
ComputedInterfaceDescriptionQueryNetworkInterfaceEdgesNode.model_rebuild()
ComputedInterfaceDescriptionQueryNetworkInterfaceEdgesNodeLink.model_rebuild()
ComputedInterfaceDescriptionQueryNetworkInterfaceEdgesNodeLinkNode.model_rebuild()
ComputedInterfaceDescriptionQueryNetworkInterfaceEdgesNodeLinkNodeEndpoints.model_rebuild()
ComputedInterfaceDescriptionQueryNetworkInterfaceEdgesNodeLinkNodeEndpointsEdges.model_rebuild()
ComputedInterfaceDescriptionQueryNetworkInterfaceEdgesNodeLinkNodeEndpointsEdgesNodeNetworkInterface.model_rebuild()
ComputedInterfaceDescriptionQueryNetworkInterfaceEdgesNodeLinkNodeEndpointsEdgesNodeNetworkInterfaceDevice.model_rebuild()
ComputedInterfaceDescriptionQueryNetworkInterfaceEdgesNodeLinkNodeEndpointsEdgesNodeNetworkInterfaceDeviceNode.model_rebuild()
