"""Render a Kubernetes cluster's Cilium BGP manifest — the artifact Vidra applies to the cluster.

The rendered body is a single multi-document YAML: one ``CiliumBGPClusterConfig`` per eligible L3
member (each member peers with its own leaf on its own /31, so a shared cluster config cannot express
it — see ``specs/004-kubernetes-cilium-bgp/research.md`` R1), followed by one shared
``CiliumBGPPeerConfig`` and one shared ``CiliumBGPAdvertisement``.

Two properties this module is responsible for:

- **It holds no selection or eligibility logic.** Which members yield a peering, and in what order, is
  :mod:`infrahub_solution_ai_dc.clusters`. Everything here is a pure mapping from a
  :class:`~infrahub_solution_ai_dc.clusters.CiliumPeering` to Cilium's field names.
- **Python serialisation, not Jinja2.** Dicts fed to ``yaml.safe_dump_all`` are valid YAML by
  construction, which is what makes the empty case (FR-005 — an all-L2 or zero-member cluster renders
  *zero* documents) correct rather than a hand-indented special case.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, cast

import yaml
from infrahub_sdk.transforms import InfrahubTransform

from infrahub_solution_ai_dc.clusters import build_cilium_peerings

from .cilium_manifest_query import CiliumManifestQuery

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from pydantic import BaseModel

    from infrahub_solution_ai_dc.clusters import CiliumPeering
    from infrahub_solution_ai_dc.protocols import NetworkServerService

#: Every rendered document is a Cilium v2 resource; the v2alpha1 resource set is superseded.
API_VERSION = "cilium.io/v2"

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


class _Absent:
    """Stands in for a relationship the query returned nothing for.

    Shaped to satisfy both readings at once — an unset to-one (``id`` is ``None``) and an empty
    to-many (``peers`` is empty) — because a null field in the response cannot tell the two apart.
    Either way the peering module reads it as absent data and omits the member rather than raising.
    """

    def __init__(self) -> None:
        self.id: str | None = None
        self.peers: list[_Related] = []


_ABSENT = _Absent()


class _Related:
    """A to-one relationship in ``RelatedNode`` shape: an ``id`` (``None`` when unset) and a ``peer``."""

    def __init__(self, node: BaseModel | None) -> None:
        self.id: str | None = None if node is None else getattr(node, "id", None)
        self.peer: _NodeView | None = None if node is None else _NodeView(node)


class _Manager:
    """A to-many relationship in ``RelationshipManager`` shape: ``peers`` holds the related nodes."""

    def __init__(self, edges: Iterable[Any]) -> None:
        self.peers = [_Related(edge.node) for edge in edges]


class _NodeView:
    """Presents a parsed GraphQL node in ``InfrahubNode`` shape.

    The peering module reads Infrahub nodes (``.peer``, ``.peers``, ``get_kind()``); a GraphQL response
    nests the same graph as ``{"node": ...}`` and ``{"edges": [...]}``. This adapter translates the
    latter into the former so the transform needs no client round trips — the query already returns
    every value a peering record needs — and so the module stays the single place that knows *which*
    values matter. It is a shape translation only: it makes no decision about any member.

    Attribute leaves are passed through untouched, since a parsed ``{"value": ...}`` model already
    exposes ``.value`` exactly as an Infrahub attribute does.
    """

    def __init__(self, model: BaseModel) -> None:
        self._model = model

    def get_kind(self) -> str:
        """Return the node's Infrahub kind, from the query's ``__typename`` selection."""
        return str(getattr(self._model, "typename__", None) or "")

    def __getattr__(self, name: str) -> Any:  # noqa: ANN401
        # Private and dunder names are never graph fields. Refusing them keeps a `hasattr` probe for
        # something like `__iter__` from resolving to the wrapped Pydantic model's own machinery, and
        # keeps a lookup before `__init__` has run from recursing.
        if name.startswith("_"):
            raise AttributeError(name)
        field: Any = getattr(self._model, name, None)
        if field is None:
            return _ABSENT
        if hasattr(field, "node"):
            return _Related(field.node)
        if hasattr(field, "edges"):
            return _Manager(field.edges or [])
        return field


def cluster_members(parsed: CiliumManifestQuery) -> list[NetworkServerService]:
    """Return the cluster's members, node-shaped, or an empty list when the cluster has none.

    A query result with no cluster edge (a name that matches nothing) is an empty cluster as far as
    rendering is concerned, so it renders an empty body rather than raising.
    """
    edges = parsed.network_kubernetes_cluster.edges
    cluster = edges[0].node if edges else None
    if cluster is None or cluster.members is None:
        return []
    return [
        cast("NetworkServerService", _NodeView(edge.node)) for edge in cluster.members.edges if edge.node is not None
    ]


def render_cluster_manifest(data: dict[str, Any], logger: logging.Logger | None = None) -> str:
    """Render one cluster's manifest from the raw ``cilium_manifest`` query result.

    The whole transform, minus the SDK plumbing: parse, hand the members to the peering module, render
    what it returns. Kept as a function so it is exercised directly by the unit tests.

    ``logger`` reaches the peering module only, where it reports each member omitted for ineligibility.
    It changes no rendered output.
    """
    return render_manifest(build_cilium_peerings(cluster_members(CiliumManifestQuery(**data)), logger))


class CiliumManifest(InfrahubTransform):
    query = "cilium_manifest"

    #: ``InfrahubTransform`` provides no logger of its own, unlike ``InfrahubGenerator``. Naming the
    #: same logger the generators use (``generators/generate_server.py``) puts a member omitted here
    #: in the same stream as the run that failed to provision it.
    logger = logging.getLogger("infrahub.tasks")

    async def transform(self, data: dict[str, Any]) -> str:
        return render_cluster_manifest(data, self.logger)
