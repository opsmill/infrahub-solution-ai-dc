from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class _ValueStr(BaseModel):
    value: str | None = None


class _ValueAny(BaseModel):
    value: Any | None = None


class _ServerNode(BaseModel):
    id: str
    hostname: _ValueStr | None = None


class _Server(BaseModel):
    node: _ServerNode | None = None


class _RackNode(BaseModel):
    id: str
    name: _ValueStr | None = None
    index: _ValueAny | None = None


class _Rack(BaseModel):
    node: _RackNode | None = None


class _DeviceNode(BaseModel):
    id: str
    hostname: _ValueStr | None = None
    role: _ValueStr | None = None


class _Device(BaseModel):
    node: _DeviceNode | None = None


class _LeafInterfaceNode(BaseModel):
    id: str
    name: _ValueStr | None = None
    role: _ValueStr | None = None
    device: _Device | None = None


class _LeafInterface(BaseModel):
    node: _LeafInterfaceNode | None = None


class _SegmentVrfRefNode(BaseModel):
    id: str


class _SegmentVrfRef(BaseModel):
    node: _SegmentVrfRefNode | None = None


class _SegmentNode(BaseModel):
    id: str
    name: _ValueStr | None = None
    vrf: _SegmentVrfRef | None = None


class _Segment(BaseModel):
    node: _SegmentNode | None = None


class _FabricNode(BaseModel):
    id: str
    name: _ValueStr | None = None
    overlay_asn: _ValueAny | None = None


class _Fabric(BaseModel):
    node: _FabricNode | None = None


class _TenantNode(BaseModel):
    id: str
    name: _ValueStr | None = None
    fabric: _Fabric | None = None


class _Tenant(BaseModel):
    node: _TenantNode | None = None


class _VrfNode(BaseModel):
    id: str
    name: _ValueStr | None = None
    tenant: _Tenant | None = None


class _Vrf(BaseModel):
    node: _VrfNode | None = None


class ServerGeneratorQueryServiceNode(BaseModel):
    id: str
    name: _ValueStr | None = None
    checksum: _ValueStr | None = None
    layer: _ValueStr | None = None
    server: _Server | None = None
    rack: _Rack | None = None
    leaf_interface: _LeafInterface | None = None
    segment: _Segment | None = None
    vrf: _Vrf | None = None


class _ServiceEdge(BaseModel):
    node: ServerGeneratorQueryServiceNode | None = None


class _Service(BaseModel):
    edges: list[_ServiceEdge] = []


class ServerGeneratorQuery(BaseModel):
    network_server_service: _Service = Field(alias="NetworkServerService")
