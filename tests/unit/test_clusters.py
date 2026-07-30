"""Tests for the cluster peering helpers (src/infrahub_solution_ai_dc/clusters.py) — US1 unit tests.

These exercise the *pure* peering module with plain stubs (no Infrahub client, no network),
mirroring tests/unit/test_servers.py. The module turns a cluster's members into the ordered
``CiliumPeering`` records the manifest transform renders, so everything asserted here is a value that
ends up in the published artifact.

Scope note: this file covers the happy path plus the two determinism properties the artifact
checksum depends on (interface selection within a member, ordering across members) — the latter both
as a selector ordering (US1) and as full record invariance under shuffled input (US2). The full
eligibility matrix of data-model.md §5 is exercised separately.
"""

from __future__ import annotations

from ipaddress import ip_interface
from typing import TYPE_CHECKING, NamedTuple, cast

from infrahub_solution_ai_dc.clusters import (
    CiliumPeering,
    build_cilium_peerings,
    instance_name,
    leaf_port_address,
    strip_prefix_length,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from infrahub_solution_ai_dc.protocols import NetworkServer, NetworkServerService

OVERLAY_ASN = 65000


class _Value(NamedTuple):
    """Stand-in for an Infrahub attribute leaf (exposes ``.value``)."""

    value: object


class _Related:
    """A to-one relationship, ``RelatedNode``-shaped: an ``id`` (``None`` when unset) and a ``peer``."""

    def __init__(self, peer: object | None) -> None:
        self.id = None if peer is None else "set"
        self.peer = peer


class _Manager:
    """A to-many relationship, ``RelationshipManager``-shaped: ``peers`` holds ``RelatedNode``s."""

    def __init__(self, peers: Sequence[object]) -> None:
        self.peers = [_Related(peer) for peer in peers]


class _IPAddressStub:
    """An IpamIPAddress stub: only ``address.value``, which carries the prefix length.

    The value is an ``IPv4Interface``, not a string, because that is what the SDK produces — it maps
    an ``IPHost`` attribute through ``ipaddress.ip_interface``.
    """

    def __init__(self, address: str) -> None:
        self.address = _Value(ip_interface(address))


class _LeafInterfaceStub:
    """The leaf end of a server link — kind ``NetworkInterface``, and the only valid address source."""

    def __init__(self, address: str | None) -> None:
        self.ip_address = _Related(_IPAddressStub(address) if address is not None else None)

    def get_kind(self) -> str:
        return "NetworkInterface"


class _ServerInterfaceStub:
    """The server end of the link — kind ``ServerInterface``, so never the peer address source.

    It carries an ``ip_address`` too (the other half of the /31), which is exactly the value picking
    the wrong end of the link would yield.
    """

    def __init__(self, name: str, own_address: str | None = None) -> None:
        self.name = _Value(name)
        self.ip_address = _Related(_IPAddressStub(own_address) if own_address is not None else None)
        self.link = _Related(None)

    def get_kind(self) -> str:
        return "ServerInterface"


class _LinkStub:
    """A NetworkLink stub: both endpoints of the server<->leaf cable."""

    def __init__(self, endpoints: Sequence[object]) -> None:
        self.endpoints = _Manager(endpoints)


class _SessionStub:
    """A NetworkBGPSession stub: the three attributes the field mapping reads."""

    def __init__(self, address_family: str, local_as: int | None, remote_as: int | None) -> None:
        self.address_family = _Value(address_family)
        self.local_as = _Value(local_as)
        self.remote_as = _Value(remote_as)


class _ServerStub:
    """A NetworkServer stub: the computed node selector plus its device-side sessions and ports."""

    def __init__(
        self,
        node_selector: str | None,
        sessions: Sequence[object],
        interfaces: Sequence[object],
        server_id: str = "server",
    ) -> None:
        self.id = server_id
        self.node_selector = _Value(node_selector)
        self.bgp_sessions = _Manager(sessions)
        self.interfaces = _Manager(interfaces)


class _ServiceStub:
    """A NetworkServerService stub: its layer and the server it resolves to."""

    def __init__(self, name: str, layer: str, server: object | None) -> None:
        self.name = _Value(name)
        self.layer = _Value(layer)
        self.server = _Related(server)


def _cabled_interface(name: str, leaf_address: str | None, own_address: str | None = None) -> _ServerInterfaceStub:
    """A server port cabled to a leaf port holding ``leaf_address`` (the /31's other half)."""
    server_end = _ServerInterfaceStub(name, own_address)
    leaf_end = _LeafInterfaceStub(leaf_address)
    server_end.link = _Related(_LinkStub([server_end, leaf_end]))
    return server_end


def _server(
    node_selector: str,
    local_as: int,
    leaf_address: str,
    interface_name: str = "eth1",
    server_id: str = "server",
) -> _ServerStub:
    """A fully-provisioned L3 member's server: one ipv4_unicast session, one cabled port."""
    return _ServerStub(
        node_selector=node_selector,
        sessions=[_SessionStub("ipv4_unicast", local_as, OVERLAY_ASN)],
        interfaces=[_cabled_interface(interface_name, leaf_address)],
        server_id=server_id,
    )


def _l3_member(name: str, node_selector: str, local_as: int, leaf_address: str) -> NetworkServerService:
    server = _server(node_selector, local_as, leaf_address, server_id=f"server-{name}")
    return cast("NetworkServerService", _ServiceStub(name, "l3", server))


class TestBuildCiliumPeerings:
    """Two eligible L3 members -> two records whose every field comes from the stored graph."""

    def test_two_eligible_members_yield_two_mapped_records(self) -> None:
        """Each field maps per data-model.md §5: ASNs from the server-side session, address from cabling."""
        members = [
            _l3_member("cilium-worker-1", "cilium-worker-1", 4200000001, "10.0.0.1/31"),
            _l3_member("cilium-worker-2", "cilium-worker-2", 4200000002, "10.0.0.3/31"),
        ]

        peerings = build_cilium_peerings(members)

        assert peerings == [
            CiliumPeering(
                node_selector="cilium-worker-1",
                local_asn=4200000001,
                peer_asn=OVERLAY_ASN,
                peer_address="10.0.0.1",
                instance_name="instance-4200000001",
            ),
            CiliumPeering(
                node_selector="cilium-worker-2",
                local_asn=4200000002,
                peer_asn=OVERLAY_ASN,
                peer_address="10.0.0.3",
                instance_name="instance-4200000002",
            ),
        ]

    def test_local_and_peer_asn_come_from_the_server_side_session(self) -> None:
        """``local_as`` is the member's own ASN and ``remote_as`` the leaf's — never swapped (SC-002)."""
        members = [_l3_member("cilium-worker-1", "cilium-worker-1", 4200000001, "10.0.0.1/31")]

        (peering,) = build_cilium_peerings(members)

        assert peering.local_asn == 4200000001
        assert peering.peer_asn == OVERLAY_ASN

    def test_peer_address_is_the_leaf_end_with_the_prefix_length_stripped(self) -> None:
        """Cilium wants a bare host address, and it must be the *leaf's* half of the /31.

        The server end of the link carries ``10.0.0.0/31``; picking that end would look plausible and
        be wrong, so the stub gives both ends an address to make the mistake detectable.
        """
        server = _ServerStub(
            node_selector="cilium-worker-1",
            sessions=[_SessionStub("ipv4_unicast", 4200000001, OVERLAY_ASN)],
            interfaces=[_cabled_interface("eth1", leaf_address="10.0.0.1/31", own_address="10.0.0.0/31")],
        )
        member = cast("NetworkServerService", _ServiceStub("cilium-worker-1", "l3", server))

        (peering,) = build_cilium_peerings([member])

        assert peering.peer_address == "10.0.0.1"

    def test_node_selector_comes_from_the_server(self) -> None:
        """The record's selector is the Server's computed ``node_selector``, not the service name."""
        server = _server("cilium-worker-1", 4200000001, "10.0.0.1/31")
        member = cast("NetworkServerService", _ServiceStub("some-other-service-name", "l3", server))

        (peering,) = build_cilium_peerings([member])

        assert peering.node_selector == "cilium-worker-1"

    def test_records_are_sorted_by_node_selector(self) -> None:
        """Across-member ordering is by ``node_selector`` regardless of fetch order (FR-008).

        Without this the artifact checksum changes on every render and Vidra re-syncs forever.
        """
        members = [
            _l3_member("cilium-worker-3", "cilium-worker-3", 4200000003, "10.0.0.5/31"),
            _l3_member("cilium-worker-1", "cilium-worker-1", 4200000001, "10.0.0.1/31"),
            _l3_member("cilium-worker-2", "cilium-worker-2", 4200000002, "10.0.0.3/31"),
        ]

        peerings = build_cilium_peerings(members)

        assert [peering.node_selector for peering in peerings] == [
            "cilium-worker-1",
            "cilium-worker-2",
            "cilium-worker-3",
        ]

    def test_shuffled_input_order_yields_identical_records(self) -> None:
        """The *whole* record list is invariant under input order, not just its ``node_selector`` column.

        Sorting by selector is only half of checksum stability: if any other field were carried over
        from a neighbouring member, the artifact would still be ordered and still churn. Reversal plus
        one rotation covers both a full flip and an off-by-one shift, and both are deterministic — a
        randomised shuffle here could pass on a lucky permutation.
        """
        members = [
            _l3_member("cilium-worker-1", "cilium-worker-1", 4200000001, "10.0.0.1/31"),
            _l3_member("cilium-worker-2", "cilium-worker-2", 4200000002, "10.0.0.3/31"),
            _l3_member("cilium-worker-3", "cilium-worker-3", 4200000003, "10.0.0.5/31"),
        ]

        expected = build_cilium_peerings(members)

        assert build_cilium_peerings(list(reversed(members))) == expected
        assert build_cilium_peerings([*members[1:], members[0]]) == expected

    def test_no_members_yields_no_records(self) -> None:
        """A zero-member cluster is valid and produces nothing to render (FR-005)."""
        assert build_cilium_peerings([]) == []


class TestLeafPortAddress:
    """Within-member interface selection — the second half of checksum stability."""

    def test_lowest_named_cabled_interface_wins_regardless_of_input_order(self) -> None:
        """Interfaces are walked in name order, not query order, so the address cannot flip.

        The spec assumes one uplink per member, but a second cabled port (management, or leftovers
        mid-move) would otherwise let ``peerAddress`` alternate between renders.
        """
        low = _cabled_interface("eth1", "10.0.0.1/31")
        high = _cabled_interface("eth2", "10.0.0.3/31")

        forward = _ServerStub("cilium-worker-1", sessions=[], interfaces=[low, high])
        reverse = _ServerStub("cilium-worker-1", sessions=[], interfaces=[high, low])

        assert leaf_port_address(cast("NetworkServer", forward)) == "10.0.0.1"
        assert leaf_port_address(cast("NetworkServer", reverse)) == "10.0.0.1"

    def test_an_uncabled_interface_is_skipped_for_the_next_candidate(self) -> None:
        """A lower-named but uncabled port does not shadow the real uplink."""
        uncabled = _ServerInterfaceStub("eth0")
        cabled = _cabled_interface("eth1", "10.0.0.1/31")

        server = _ServerStub("cilium-worker-1", sessions=[], interfaces=[uncabled, cabled])

        assert leaf_port_address(cast("NetworkServer", server)) == "10.0.0.1"


class TestStripPrefixLength:
    def test_prefix_length_is_removed(self) -> None:
        """``peerAddress`` is a bare host address — ``10.0.0.1``, never ``10.0.0.1/31``."""
        assert strip_prefix_length("10.0.0.1/31") == "10.0.0.1"

    def test_a_bare_address_is_unchanged(self) -> None:
        """An address stored without a prefix length passes through untouched."""
        assert strip_prefix_length("10.0.0.1") == "10.0.0.1"

    def test_an_sdk_iphost_value_is_handled(self) -> None:
        """The SDK parses an ``IPHost`` attribute into an ``IPv4Interface``, not a string.

        ``Attribute.__init__`` maps ``IPHost`` through ``ipaddress.ip_interface``, so a value read off
        an ``InfrahubNode`` is an interface object. Treating it as a string would raise ``AttributeError``.
        """
        assert strip_prefix_length(ip_interface("10.0.0.1/31")) == "10.0.0.1"


class TestInstanceName:
    def test_instance_name_is_derived_from_the_local_asn(self) -> None:
        """Deterministic and unique within the document, which is all Cilium requires."""
        assert instance_name(4200000001) == "instance-4200000001"
