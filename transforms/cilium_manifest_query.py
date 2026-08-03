"""Response model for ``transforms/cilium_manifest.gql``.

Hand-written to the same shape a generated model would take (``_Value*`` leaves, ``_``-prefixed
private nesting, ``Field(alias=...)`` for the GraphQL keys), matching
``transforms/fabric_cabling_plan_query.py`` and ``generators/generate_server_query.py``. Used with
``convert_query_response: false``, so the transform instantiates it from the raw query result.

Every field is optional with a default. A cluster mid-provisioning legitimately returns a null
``server``, no sessions, or an uncabled interface, and the manifest must render the members that *are*
complete rather than fail to parse (FR-004/FR-005).
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class _ValueStr(BaseModel):
    value: str | None = None


class _ValueInt(BaseModel):
    value: int | None = None


class _IPAddressNode(BaseModel):
    id: str | None = None
    address: _ValueStr | None = None


class _IPAddress(BaseModel):
    node: _IPAddressNode | None = None


class _EndpointNode(BaseModel):
    """One end of a link. ``ip_address`` is selected only on the ``NetworkInterface`` end."""

    id: str | None = None
    typename__: str | None = Field(default=None, alias="__typename")
    ip_address: _IPAddress | None = None


class _EndpointEdge(BaseModel):
    node: _EndpointNode | None = None


class _Endpoints(BaseModel):
    edges: list[_EndpointEdge] = []


class _LinkNode(BaseModel):
    id: str | None = None
    endpoints: _Endpoints | None = None


class _Link(BaseModel):
    node: _LinkNode | None = None


class _ServerInterfaceNode(BaseModel):
    id: str | None = None
    name: _ValueStr | None = None
    link: _Link | None = None


class _ServerInterfaceEdge(BaseModel):
    node: _ServerInterfaceNode | None = None


class _ServerInterfaces(BaseModel):
    edges: list[_ServerInterfaceEdge] = []


class _SessionNode(BaseModel):
    id: str | None = None
    address_family: _ValueStr | None = None
    local_as: _ValueInt | None = None
    remote_as: _ValueInt | None = None


class _SessionEdge(BaseModel):
    node: _SessionNode | None = None


class _Sessions(BaseModel):
    edges: list[_SessionEdge] = []


class _ServerNode(BaseModel):
    id: str | None = None
    hostname: _ValueStr | None = None
    node_selector: _ValueStr | None = None
    asn: _ValueInt | None = None
    bgp_sessions: _Sessions | None = None
    interfaces: _ServerInterfaces | None = None


class _Server(BaseModel):
    node: _ServerNode | None = None


class _MemberNode(BaseModel):
    id: str | None = None
    name: _ValueStr | None = None
    layer: _ValueStr | None = None
    server: _Server | None = None


class _MemberEdge(BaseModel):
    node: _MemberNode | None = None


class _Members(BaseModel):
    edges: list[_MemberEdge] = []


class _ClusterNode(BaseModel):
    id: str | None = None
    name: _ValueStr | None = None
    members: _Members | None = None


class _ClusterEdge(BaseModel):
    node: _ClusterNode | None = None


class _Cluster(BaseModel):
    edges: list[_ClusterEdge] = []


class CiliumManifestQuery(BaseModel):
    network_kubernetes_cluster: _Cluster = Field(alias="NetworkKubernetesCluster")
