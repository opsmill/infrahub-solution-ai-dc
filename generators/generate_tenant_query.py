from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class _ValueStr(BaseModel):
    value: str | None = None


class _ValueAny(BaseModel):
    value: Any | None = None


class _SubnetNode(BaseModel):
    id: str | None = None
    prefix: _ValueAny | None = None


class _Subnet(BaseModel):
    node: _SubnetNode | None = None


class _GatewayNode(BaseModel):
    id: str | None = None
    address: _ValueStr | None = None


class _Gateway(BaseModel):
    node: _GatewayNode | None = None


class _RackNode(BaseModel):
    id: str
    name: _ValueStr | None = None


class _RackEdge(BaseModel):
    node: _RackNode | None = None


class _Racks(BaseModel):
    edges: list[_RackEdge] = []


class _FabricNode(BaseModel):
    id: str
    name: _ValueStr | None = None
    overlay_asn: _ValueAny | None = None


class _Fabric(BaseModel):
    node: _FabricNode | None = None


class TenantGeneratorQuerySegmentNode(BaseModel):
    id: str
    name: _ValueStr | None = None
    vlan_id: _ValueAny | None = None
    l2vni: _ValueAny | None = None
    route_target: _ValueStr | None = None
    routed: _ValueAny | None = None
    subnet: _Subnet | None = None
    gateway: _Gateway | None = None
    racks: _Racks | None = None


class _SegmentEdge(BaseModel):
    node: TenantGeneratorQuerySegmentNode | None = None


class _Segments(BaseModel):
    edges: list[_SegmentEdge] = []


class TenantGeneratorQueryVrfNode(BaseModel):
    id: str
    name: _ValueStr | None = None
    l3vni: _ValueAny | None = None
    l3_vlan_id: _ValueAny | None = None
    route_target: _ValueStr | None = None
    segments: _Segments | None = None


class _VrfEdge(BaseModel):
    node: TenantGeneratorQueryVrfNode | None = None


class _Vrfs(BaseModel):
    edges: list[_VrfEdge] = []


class TenantGeneratorQueryTenantNode(BaseModel):
    id: str
    name: _ValueStr | None = None
    checksum: _ValueStr | None = None
    fabric: _Fabric | None = None
    vrfs: _Vrfs | None = None


class _TenantEdge(BaseModel):
    node: TenantGeneratorQueryTenantNode | None = None


class _Tenant(BaseModel):
    edges: list[_TenantEdge] = []


class TenantGeneratorQuery(BaseModel):
    network_tenant: _Tenant = Field(alias="NetworkTenant")
