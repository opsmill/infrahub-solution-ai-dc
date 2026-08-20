"""Render a Kubernetes cluster's Cilium BGP manifest — the artifact Vidra applies to the cluster.

The rendered body is a single multi-document YAML: one ``CiliumBGPClusterConfig`` per eligible L3
member (each member peers with its own leaf on its own /31, so a shared cluster config cannot express
it — see ``specs/004-kubernetes-cilium-bgp/research.md`` R1), followed by one shared
``CiliumBGPPeerConfig`` and one shared ``CiliumBGPAdvertisement``.

Two properties this module is responsible for:

- **It holds no eligibility logic.** Which members yield a peering, and in what order, is
  :mod:`infrahub_solution_ai_dc.clusters`. This module reads the query result into the
  :class:`~infrahub_solution_ai_dc.clusters.MemberFacts` that module decides on, and maps whatever
  it returns onto Cilium's field names. Reading the response lives here because the response shape
  is this module's business — the rules stay free of it.
- **Python serialisation, not Jinja2.** Dicts fed to ``yaml.safe_dump_all`` are valid YAML by
  construction, which is what makes the empty case (FR-005 — an all-L2 or zero-member cluster renders
  *zero* documents) correct rather than a hand-indented special case.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import yaml
from infrahub_sdk.transforms import InfrahubTransform

from infrahub_solution_ai_dc.clusters import SERVER_ADDRESS_FAMILY, MemberFacts, build_cilium_peerings

from .cilium_manifest_query import (
    CiliumManifestQuery,
    _MemberNode,
    _ServerInterfaceNode,
    _ServerNode,
    _SessionNode,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from infrahub_solution_ai_dc.clusters import CiliumPeering

#: Every rendered document is a Cilium v2 resource; the v2alpha1 resource set is superseded.
API_VERSION = "cilium.io/v2"

#: The kind of the *leaf* end of a server attachment link; the server end is a ``ServerInterface``.
LEAF_INTERFACE_KIND = "NetworkInterface"

#: The node label the operator applies as ``infrahub.io/server=<node_selector>``.
NODE_SELECTOR_LABEL = "infrahub.io/server"

#: ``metadata.name`` of the shared peer config, referenced by every cluster config's ``peerConfigRef``.
PEER_CONFIG_NAME = "cilium-peer"

#: ``metadata.name`` of the shared advertisement.
ADVERTISEMENT_NAME = "cilium-bgp-advertisements"

#: The peer config selects advertisements by *label*, not by name, so both sides must agree. Held as
#: key/value rather than as a shared dict so each document gets its own object to serialise.
ADVERTISE_LABEL_KEY = "advertise"
ADVERTISE_LABEL_VALUE = "cilium-bgp"


def peer_name(peer_asn: int) -> str:
    """Return the name of a member's single peer — the leaf it is cabled to.

    Cilium requires it unique within the BGP instance only, so deriving it from the leaf's AS is both
    sufficient and deterministic. Not a field of ``CiliumPeering``: it is a rendering concern, and the
    record already carries everything it derives from.
    """
    return f"peer-{peer_asn}-leaf"


def cluster_config(peering: CiliumPeering) -> dict[str, Any]:
    """Return the ``CiliumBGPClusterConfig`` document for one eligible L3 member.

    ``localPort`` is deliberately absent: setting it makes Cilium listen, which needs
    ``CAP_NET_BIND_SERVICE`` granted through a Helm value this feature does not own. Omitted, Cilium
    initiates outbound only and the session still establishes. ``peerConfigRef.group``/``kind`` are
    likewise omitted — their defaults are exactly ``cilium.io``/``CiliumBGPPeerConfig``.
    """
    return {
        "apiVersion": API_VERSION,
        "kind": "CiliumBGPClusterConfig",
        "metadata": {"name": peering.node_selector},
        "spec": {
            "nodeSelector": {"matchLabels": {NODE_SELECTOR_LABEL: peering.node_selector}},
            "bgpInstances": [
                {
                    "name": peering.instance_name,
                    "localASN": peering.local_asn,
                    "peers": [
                        {
                            "name": peer_name(peering.peer_asn),
                            "peerASN": peering.peer_asn,
                            "peerAddress": peering.peer_address,
                            "peerConfigRef": {"name": PEER_CONFIG_NAME},
                        }
                    ],
                }
            ],
        },
    }


def peer_config() -> dict[str, Any]:
    """Return the shared ``CiliumBGPPeerConfig`` document.

    ``ipv4``/``unicast`` mirrors the stored session's ``ipv4_unicast`` address family. ``timers``,
    ``authSecretRef``, ``ebgpMultihop``, ``gracefulRestart`` and ``transport`` are omitted: the source
    of truth holds no data for them, so defaulting them here would assert configuration Infrahub does
    not know it holds.
    """
    return {
        "apiVersion": API_VERSION,
        "kind": "CiliumBGPPeerConfig",
        "metadata": {"name": PEER_CONFIG_NAME},
        "spec": {
            "families": [
                {
                    "afi": "ipv4",
                    "safi": "unicast",
                    "advertisements": {"matchLabels": {ADVERTISE_LABEL_KEY: ADVERTISE_LABEL_VALUE}},
                }
            ]
        },
    }


def advertisement() -> dict[str, Any]:
    """Return the shared ``CiliumBGPAdvertisement`` document.

    Its labels are what :func:`peer_config`'s selector matches. ``PodCIDR`` is the only advertisement
    type: advertising Services / LoadBalancer IPs is out of scope, and there is no data model for BGP
    attributes such as communities or local preference.
    """
    return {
        "apiVersion": API_VERSION,
        "kind": "CiliumBGPAdvertisement",
        "metadata": {
            "name": ADVERTISEMENT_NAME,
            "labels": {ADVERTISE_LABEL_KEY: ADVERTISE_LABEL_VALUE},
        },
        "spec": {"advertisements": [{"advertisementType": "PodCIDR"}]},
    }


def render_manifest(peerings: Sequence[CiliumPeering]) -> str:
    """Return the multi-document YAML body for a cluster's peerings.

    ``N`` peerings render ``N + 2`` documents in a fixed order — cluster configs (already ordered by
    ``node_selector``), then the peer config, then the advertisement. The order is fixed so an
    unchanged fabric renders byte-identically, which is what makes Vidra's checksum comparison
    meaningful.

    With no peerings the body is **empty**, not the two shared documents on their own: a peer config
    nothing references and an advertisement nothing advertises would be inert clutter (FR-005).
    """
    documents = [cluster_config(peering) for peering in peerings]
    if documents:
        documents += [peer_config(), advertisement()]
    return str(yaml.safe_dump_all(documents, sort_keys=False))


def _leaf_address_behind(interface: _ServerInterfaceNode) -> str | None:
    """Return the address of the leaf port cabled to ``interface``, or ``None`` when there is none.

    The far end is discriminated by kind: a server attachment link joins a ``ServerInterface`` to a
    ``NetworkInterface``, and only the latter is the leaf. Taking the wrong end would yield the
    *server's* own half of the /31 — a plausible-looking but wrong ``peerAddress``.
    """
    link = interface.link.node if interface.link else None
    if link is None or link.endpoints is None:
        return None

    for edge in link.endpoints.edges:
        endpoint = edge.node
        if endpoint is None or endpoint.typename__ != LEAF_INTERFACE_KIND:
            continue
        address = endpoint.ip_address.node if endpoint.ip_address else None
        if address is not None and address.address is not None and address.address.value:
            return address.address.value
    return None


def _leaf_port_address(server: _ServerNode) -> str | None:
    """Return the host address of the leaf port this server is cabled to, or ``None`` if uncabled.

    ``NetworkBGPSession`` stores no addresses at all, so ``peerAddress`` comes from the cabling:
    server -> ``interfaces`` -> ``link`` -> ``endpoints`` -> the leaf ``NetworkInterface`` ->
    ``ip_address``. Reading it from the cabling is also what makes the value follow a move for free —
    the link is what moves.

    Interfaces are walked in **name order** and the first one resolving to a leaf address wins — the
    within-member half of checksum stability. The spec assumes one uplink per member, so in practice
    there is one candidate; a second cabled port (a management port, or leftovers mid-move) would
    otherwise let the rendered address flip between renders and churn the artifact.

    Ordering is a plain lexicographic sort on the interface name rather than
    ``netutils.sort_interface_list`` (which ``servers.py`` uses for leaf ports): server interface
    names are not fabric-generated, and ``sort_interface_list`` raises ``ValueError`` on names it
    cannot parse and silently drops others. Either behaviour would break the peering module's
    contract of omitting a member rather than failing the whole cluster's artifact.
    """
    if server.interfaces is None:
        return None

    interfaces = [edge.node for edge in server.interfaces.edges if edge.node is not None]
    for interface in sorted(interfaces, key=lambda node: (node.name.value if node.name else "") or ""):
        address = _leaf_address_behind(interface)
        if address is not None:
            return address
    return None


def _server_side_session(server: _ServerNode) -> _SessionNode | None:
    """Return the member's own eBGP session — the single object both ASNs come from.

    ``NetworkServer.bgp_sessions`` is the inverse of ``NetworkBGPSession.device`` (schema identifier
    ``device__bgp_session``), so every session reachable here is already the *server* side of a pair:
    its ``local_as`` is the member's own ASN and its ``remote_as`` is the leaf's local AS. Returns
    ``None`` when the member has no ``ipv4_unicast`` session yet, i.e. it is still mid-provisioning.
    """
    if server.bgp_sessions is None:
        return None

    for edge in server.bgp_sessions.edges:
        session = edge.node
        if session is not None and session.address_family and session.address_family.value == SERVER_ADDRESS_FAMILY:
            return session
    return None


def _facts_for(member: _MemberNode) -> MemberFacts:
    """Read one member's parsed subtree into the plain values the peering rules decide on.

    Reads defensively throughout: a member with nothing resolved is exactly the case the rules exist
    to omit, so a missing field must produce an absent fact rather than an ``AttributeError``.
    """
    name = (member.name.value if member.name else None) or "<unnamed>"
    layer = member.layer.value if member.layer else None
    server = member.server.node if member.server else None
    if server is None:
        return MemberFacts(name=name, layer=layer, server_present=False)

    session = _server_side_session(server)
    return MemberFacts(
        name=name,
        layer=layer,
        server_present=True,
        session_present=session is not None,
        local_asn=session.local_as.value if session and session.local_as else None,
        peer_asn=session.remote_as.value if session and session.remote_as else None,
        node_selector=server.node_selector.value if server.node_selector else None,
        leaf_address=_leaf_port_address(server),
    )


def cluster_member_facts(parsed: CiliumManifestQuery) -> list[MemberFacts]:
    """Return the facts for every member of the cluster, or an empty list when it has none.

    A query result with no cluster edge (a name that matches nothing) is an empty cluster as far as
    rendering is concerned, so it renders an empty body rather than raising.
    """
    edges = parsed.network_kubernetes_cluster.edges
    cluster = edges[0].node if edges else None
    if cluster is None or cluster.members is None:
        return []
    return [_facts_for(edge.node) for edge in cluster.members.edges if edge.node is not None]


def render_cluster_manifest(data: dict[str, Any], logger: logging.Logger | None = None) -> str:
    """Render one cluster's manifest from the raw ``cilium_manifest`` query result.

    The whole transform, minus the SDK plumbing: parse, hand the members to the peering module, render
    what it returns. Kept as a function so it is exercised directly by the unit tests.

    ``logger`` reaches the peering module only, where it reports each member omitted for ineligibility.
    It changes no rendered output.
    """
    return render_manifest(build_cilium_peerings(cluster_member_facts(CiliumManifestQuery(**data)), logger))


class CiliumManifest(InfrahubTransform):
    query = "cilium_manifest"

    #: ``InfrahubTransform`` provides no logger of its own, unlike ``InfrahubGenerator``. Naming the
    #: same logger the generators use (``generators/generate_server.py``) puts a member omitted here
    #: in the same stream as the run that failed to provision it.
    logger = logging.getLogger("infrahub.tasks")

    async def transform(self, data: dict[str, Any]) -> str:
        return render_cluster_manifest(data, self.logger)
