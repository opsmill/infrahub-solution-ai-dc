"""Cluster peering helpers — turn a Kubernetes cluster's members into Cilium BGP peering records.

Every function here is **pure**: it takes already-fetched node-like objects (no ``client``, no
``await``, no network) and returns plain values, mirroring the pure helpers in
:mod:`infrahub_solution_ai_dc.servers` and :mod:`infrahub_solution_ai_dc.overlay`. That is what keeps
the manifest transform free of selection logic and this module unit-testable with simple stubs.

Two ordering guarantees live here, and both exist for the same reason — the rendered artifact's
checksum is what Vidra compares to decide whether to re-sync, so an unchanged fabric must render
byte-identically:

- **Across members**: :func:`build_cilium_peerings` sorts by ``node_selector``.
- **Within a member**: :func:`leaf_port_address` walks the server's interfaces in name order rather
  than in query order.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple, TypeVar, cast

if TYPE_CHECKING:
    from collections.abc import Iterable
    from ipaddress import IPv4Interface, IPv6Interface

    from infrahub_sdk.node import RelatedNode, RelatedNodeSync

    from .protocols import (
        NetworkBGPSession,
        NetworkInterface,
        NetworkServer,
        NetworkServerService,
        ServerInterface,
    )

#: The address family of the server<->leaf eBGP session the generator writes (``servers.py``).
SERVER_ADDRESS_FAMILY = "ipv4_unicast"

#: The kind of the *leaf* end of a server attachment link; the server end is a ``ServerInterface``.
LEAF_INTERFACE_KIND = "NetworkInterface"

_PeerT = TypeVar("_PeerT")


class CiliumPeering(NamedTuple):
    """One eligible L3 member's peering values, as the Cilium manifest renders them.

    An in-memory record, not an Infrahub node — the intermediate value that keeps selection out of
    the renderer (``data-model.md`` §5), following the ``ProcessedInputData`` convention in
    ``transforms/cabling_plan.py``.

    ``local_asn`` and ``peer_asn`` both come from the member's **server-side** BGP session, so the
    two cannot disagree with the leaf's rendered config. ``peer_address`` is the leaf port's host
    address with no prefix length: Cilium expects ``10.0.0.1``, never ``10.0.0.1/31``.
    """

    node_selector: str
    local_asn: int
    peer_asn: int
    peer_address: str
    instance_name: str


def instance_name(local_asn: int) -> str:
    """Return the BGP instance name for a member, derived from its own ASN.

    Cilium requires the name to be unique within its document only, so deriving it from the member's
    ASN is both sufficient and deterministic.
    """
    return f"instance-{local_asn}"


def strip_prefix_length(address: str | IPv4Interface | IPv6Interface) -> str:
    """Return the host part of an interface address — ``10.0.0.1/31`` becomes ``10.0.0.1``.

    Infrahub stores an interface address with its prefix length; Cilium's ``peerAddress`` is a bare
    address and rejects the CIDR form.

    Both input shapes occur: the SDK parses an ``IPHost`` attribute through ``ipaddress.ip_interface``,
    so a value read off an ``InfrahubNode`` is an ``IPv4Interface``/``IPv6Interface``, while the same
    field read out of raw GraphQL data is a string. Both stringify to the CIDR form, so one split
    handles both.
    """
    return str(address).split("/", 1)[0]


def _related_peer(related: RelatedNode[_PeerT] | RelatedNodeSync[_PeerT]) -> _PeerT | None:
    """Return a to-one relationship's peer node, or ``None`` when the relationship is unset.

    Uses the same "is this relationship set" test as ``servers.py`` (a non-null ``id``) so an unset
    ``server``/``link``/``ip_address`` reads as absent data rather than raising.
    """
    if getattr(related, "id", None) is None:
        return None
    return related.peer


def server_side_session(server: NetworkServer) -> NetworkBGPSession | None:
    """Return the member's own eBGP session — the single object both ASNs come from.

    ``NetworkServer.bgp_sessions`` is the inverse of ``NetworkBGPSession.device`` (schema identifier
    ``device__bgp_session``), so every session reachable here is already the *server* side of a pair:
    its ``local_as`` is the member's own ASN and its ``remote_as`` is the leaf's local AS. Returns
    ``None`` when the member has no ``ipv4_unicast`` session yet, i.e. it is still mid-provisioning.
    """
    for related in server.bgp_sessions.peers:
        session = _related_peer(related)
        if session is not None and session.address_family.value == SERVER_ADDRESS_FAMILY:
            return session
    return None


def _leaf_address_behind(interface: ServerInterface) -> str | None:
    """Return the address of the leaf port cabled to ``interface``, or ``None`` when there is none.

    The far end is discriminated by kind: a server attachment link joins a ``ServerInterface`` to a
    ``NetworkInterface``, and only the latter is the leaf. Taking the wrong end would yield the
    *server's* own half of the /31 — a plausible-looking but wrong ``peerAddress``.
    """
    link = _related_peer(interface.link)
    if link is None:
        return None

    for related in link.endpoints.peers:
        endpoint = _related_peer(related)
        if endpoint is None or endpoint.get_kind() != LEAF_INTERFACE_KIND:
            continue
        # `endpoints` is typed to the NetworkEndpoint generic, which carries no `ip_address`; the kind
        # check above is what establishes this end is the leaf's NetworkInterface (as cabling_plan.py does).
        leaf_interface = cast("NetworkInterface", endpoint)
        ip_address = _related_peer(leaf_interface.ip_address)
        if ip_address is not None:
            return strip_prefix_length(ip_address.address.value)
    return None


def leaf_port_address(server: NetworkServer) -> str | None:
    """Return the host address of the leaf port this server is cabled to, or ``None`` if uncabled.

    ``NetworkBGPSession`` stores no addresses at all, so ``peerAddress`` comes from the cabling:
    server -> ``interfaces`` -> ``link`` -> ``endpoints`` -> the leaf ``NetworkInterface`` ->
    ``ip_address``. Reading it from the cabling is also what makes the value follow a move for free —
    the link is what moves.

    Interfaces are walked in **name order** and the first one resolving to a leaf address wins. The
    spec assumes one uplink per member, so in practice there is one candidate; a second cabled port
    (a management port, or leftovers mid-move) would otherwise let the rendered address flip between
    renders and churn the artifact checksum.

    Ordering is a plain lexicographic sort on the interface name rather than
    ``netutils.sort_interface_list`` (which ``servers.py`` uses for leaf ports): server interface
    names are not fabric-generated, and ``sort_interface_list`` raises ``ValueError`` on names it
    cannot parse and silently drops others. Either behaviour would break this module's contract of
    omitting a member rather than failing the whole cluster's artifact.
    """
    interfaces = [interface for related in server.interfaces.peers if (interface := _related_peer(related))]
    for interface in sorted(interfaces, key=lambda interface: interface.name.value):
        address = _leaf_address_behind(interface)
        if address is not None:
            return address
    return None


def peering_for_member(service: NetworkServerService) -> CiliumPeering | None:
    """Return the ``CiliumPeering`` for one cluster member, or ``None`` when it yields none.

    A member with incomplete data is **omitted, never raised on** (FR-004/FR-005): one member still
    mid-provisioning must not withhold valid config from the rest of the cluster.
    """
    server = _related_peer(service.server)
    if server is None:
        return None

    session = server_side_session(server)
    if session is None:
        return None

    local_asn = session.local_as.value
    peer_asn = session.remote_as.value
    node_selector = server.node_selector.value
    if local_asn is None or peer_asn is None or node_selector is None:
        return None

    peer_address = leaf_port_address(server)
    if peer_address is None:
        return None

    return CiliumPeering(
        node_selector=node_selector,
        local_asn=local_asn,
        peer_asn=peer_asn,
        peer_address=peer_address,
        instance_name=instance_name(local_asn),
    )


def build_cilium_peerings(members: Iterable[NetworkServerService]) -> list[CiliumPeering]:
    """Return the cluster's peering records, ordered by ``node_selector``.

    Members yielding no record are dropped, so an empty cluster — or one whose members are all
    ineligible — returns an empty list rather than raising (FR-005).
    """
    peerings = [peering for member in members if (peering := peering_for_member(member)) is not None]
    return sorted(peerings, key=lambda peering: peering.node_selector)
