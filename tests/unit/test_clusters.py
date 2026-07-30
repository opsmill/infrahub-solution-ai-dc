"""Tests for the cluster peering helpers (src/infrahub_solution_ai_dc/clusters.py) — US1 and US3 unit tests.

These exercise the *pure* peering module with plain stubs (no Infrahub client, no network),
mirroring tests/unit/test_servers.py. The module turns a cluster's members into the ordered
``CiliumPeering`` records the manifest transform renders, so everything asserted here is a value that
ends up in the published artifact.

Scope note: this file covers the happy path, the two determinism properties the artifact checksum
depends on (interface selection within a member, ordering across members) — the latter both as a
selector ordering (US1) and as full record invariance under shuffled input (US2) — and the full
eligibility matrix of data-model.md §5 (US3, at the bottom). Whether the *rendered body* leaves an
ineligible member out is tests/unit/test_cilium_manifest.py; here it is whether the record exists.
"""

from __future__ import annotations

import logging
from ipaddress import ip_interface
from typing import TYPE_CHECKING, NamedTuple, cast

import pytest

from infrahub_solution_ai_dc.clusters import (
    OMISSION_NO_ASN,
    OMISSION_NO_LEAF_ADDRESS,
    OMISSION_NO_NODE_SELECTOR,
    OMISSION_NO_SERVER,
    OMISSION_NO_SESSION,
    OMISSION_NOT_L3,
    CiliumPeering,
    build_cilium_peerings,
    instance_name,
    leaf_port_address,
    strip_prefix_length,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

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


def _eligible_member() -> NetworkServerService:
    """The reference eligible member, for contrasting against each ineligible one."""
    return _l3_member("cilium-worker-1", "cilium-worker-1", 4200000001, "10.0.0.1/31")


# --- The ineligible members, one per eligibility check of data-model.md §5 -------------------------
#
# Each builder makes a member that fails exactly one check and satisfies every other, so a test that
# sees it omitted has isolated that check. `_l2_member` in particular is fully provisioned — its
# server has an ipv4_unicast session with both ASNs and a cabled leaf port — because "L2 but
# otherwise complete" is the only shape that can tell a layer filter apart from the missing-data
# filters that were already in place.


def _l2_member() -> NetworkServerService:
    """Check 1: an L2 member whose data is otherwise complete. It has no BGP to express."""
    server = _server("cilium-worker-l2", 4200000009, "10.0.0.9/31", server_id="server-cilium-worker-l2")
    return cast("NetworkServerService", _ServiceStub("cilium-worker-l2", "l2", server))


def _member_without_server() -> NetworkServerService:
    """Check 2: the service's ``server`` relationship is unset — the generator has not run yet."""
    return cast("NetworkServerService", _ServiceStub("no-server", "l3", None))


def _member_without_any_session() -> NetworkServerService:
    """Check 3: the server exists and is cabled, but no session has been written yet."""
    server = _ServerStub("no-session", sessions=[], interfaces=[_cabled_interface("eth1", "10.0.0.11/31")])
    return cast("NetworkServerService", _ServiceStub("no-session", "l3", server))


def _member_without_an_ipv4_unicast_session() -> NetworkServerService:
    """Check 3: the server has a session, but of another address family, so it is not the one."""
    server = _ServerStub(
        "wrong-address-family",
        sessions=[_SessionStub("l2vpn_evpn", 4200000013, OVERLAY_ASN)],
        interfaces=[_cabled_interface("eth1", "10.0.0.13/31")],
    )
    return cast("NetworkServerService", _ServiceStub("wrong-address-family", "l3", server))


def _member_with_a_null_local_as() -> NetworkServerService:
    """Check 4: no ``localASN`` to render — a half-written session."""
    server = _ServerStub(
        "null-local-as",
        sessions=[_SessionStub("ipv4_unicast", None, OVERLAY_ASN)],
        interfaces=[_cabled_interface("eth1", "10.0.0.15/31")],
    )
    return cast("NetworkServerService", _ServiceStub("null-local-as", "l3", server))


def _member_with_a_null_remote_as() -> NetworkServerService:
    """Check 4: no ``peerASN`` to render."""
    server = _ServerStub(
        "null-remote-as",
        sessions=[_SessionStub("ipv4_unicast", 4200000017, None)],
        interfaces=[_cabled_interface("eth1", "10.0.0.17/31")],
    )
    return cast("NetworkServerService", _ServiceStub("null-remote-as", "l3", server))


def _member_without_a_node_selector() -> NetworkServerService:
    """Not one of the five checks, but the same treatment: no selector, no document to name."""
    server = _ServerStub(
        None,
        sessions=[_SessionStub("ipv4_unicast", 4200000019, OVERLAY_ASN)],
        interfaces=[_cabled_interface("eth1", "10.0.0.19/31")],
    )
    return cast("NetworkServerService", _ServiceStub("no-node-selector", "l3", server))


def _member_with_no_interfaces() -> NetworkServerService:
    """Check 5: nothing is cabled yet, so there is no leaf port to peer with."""
    server = _ServerStub(
        "no-interfaces",
        sessions=[_SessionStub("ipv4_unicast", 4200000021, OVERLAY_ASN)],
        interfaces=[],
    )
    return cast("NetworkServerService", _ServiceStub("no-interfaces", "l3", server))


def _member_with_an_uncabled_interface() -> NetworkServerService:
    """Check 5: the port exists but no link reaches a leaf."""
    server = _ServerStub(
        "uncabled",
        sessions=[_SessionStub("ipv4_unicast", 4200000023, OVERLAY_ASN)],
        interfaces=[_ServerInterfaceStub("eth1")],
    )
    return cast("NetworkServerService", _ServiceStub("uncabled", "l3", server))


def _member_whose_leaf_port_has_no_ip() -> NetworkServerService:
    """Check 5: cabled to a leaf port that holds no address — the /31 is not allocated yet."""
    server = _ServerStub(
        "no-leaf-ip",
        sessions=[_SessionStub("ipv4_unicast", 4200000025, OVERLAY_ASN)],
        interfaces=[_cabled_interface("eth1", leaf_address=None)],
    )
    return cast("NetworkServerService", _ServiceStub("no-leaf-ip", "l3", server))


#: Every ineligible shape as (test id, builder, the reason the module must report for it).
INELIGIBLE_CASES: list[tuple[str, Callable[[], NetworkServerService], str]] = [
    ("l2-member", _l2_member, OMISSION_NOT_L3),
    ("no-server", _member_without_server, OMISSION_NO_SERVER),
    ("no-session", _member_without_any_session, OMISSION_NO_SESSION),
    ("wrong-address-family", _member_without_an_ipv4_unicast_session, OMISSION_NO_SESSION),
    ("null-local-as", _member_with_a_null_local_as, OMISSION_NO_ASN),
    ("null-remote-as", _member_with_a_null_remote_as, OMISSION_NO_ASN),
    ("no-node-selector", _member_without_a_node_selector, OMISSION_NO_NODE_SELECTOR),
    ("no-interfaces", _member_with_no_interfaces, OMISSION_NO_LEAF_ADDRESS),
    ("uncabled-interface", _member_with_an_uncabled_interface, OMISSION_NO_LEAF_ADDRESS),
    ("leaf-port-without-ip", _member_whose_leaf_port_has_no_ip, OMISSION_NO_LEAF_ADDRESS),
]

#: Builder plus expected reason, for the omission-logging tests.
INELIGIBLE_MEMBERS = [pytest.param(builder, reason, id=case_id) for case_id, builder, reason in INELIGIBLE_CASES]

#: Just the builder, for the tests that do not care which check was failed.
INELIGIBLE_BUILDERS = [pytest.param(builder, id=case_id) for case_id, builder, _ in INELIGIBLE_CASES]


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


class TestEligibility:
    """The full exclusion matrix of data-model.md §5 (FR-004, FR-005, US3).

    Every case is a member that must be dropped and must not raise. The two properties are asserted
    separately on purpose: a filter that raised would also produce no record, so "omitted" alone
    cannot tell an omission apart from a failure that took the whole cluster's artifact with it.
    """

    @pytest.mark.parametrize("build_member", INELIGIBLE_BUILDERS)
    def test_an_ineligible_member_yields_no_record(self, build_member: Callable[[], NetworkServerService]) -> None:
        """Each failed check omits the member — and only that member."""
        assert build_cilium_peerings([build_member()]) == []

    @pytest.mark.parametrize("build_member", INELIGIBLE_BUILDERS)
    def test_an_ineligible_member_does_not_suppress_an_eligible_one(
        self, build_member: Callable[[], NetworkServerService]
    ) -> None:
        """The reason omission beats raising: one mid-provisioning member must not withhold the rest.

        Asserting the surviving record in full also rules out the ineligible member leaking a field
        into its neighbour.
        """
        peerings = build_cilium_peerings([build_member(), _eligible_member()])

        assert peerings == [
            CiliumPeering(
                node_selector="cilium-worker-1",
                local_asn=4200000001,
                peer_asn=OVERLAY_ASN,
                peer_address="10.0.0.1",
                instance_name="instance-4200000001",
            )
        ]

    def test_a_cluster_of_only_ineligible_members_yields_no_records_and_no_error(self) -> None:
        """The all-L2 / all-incomplete cluster: an empty list, never an exception (FR-005)."""
        members = [builder() for _, builder, _ in INELIGIBLE_CASES]

        assert build_cilium_peerings(members) == []

    def test_an_l2_member_is_dropped_even_though_its_data_is_complete(self) -> None:
        """The layer check is load-bearing on its own, not a by-product of missing data (FR-004).

        ``_l2_member``'s server carries a complete ipv4_unicast session and a cabled leaf port, so
        every other check passes and only ``layer`` can be what excludes it.
        """
        assert build_cilium_peerings([_l2_member()]) == []


class TestOmissionLogging:
    """Omission is silent in the artifact but not in the logs (critique finding E2).

    Without a log line a permanently broken member is detectable only by comparing member count to
    document count by hand. These tests pin the line down without letting it change any output.
    """

    @pytest.mark.parametrize(("build_member", "expected_reason"), INELIGIBLE_MEMBERS)
    def test_each_omitted_member_is_logged_with_the_check_it_failed(
        self,
        build_member: Callable[[], NetworkServerService],
        expected_reason: str,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """One line per omitted member, naming the member and the specific check.

        The reason matters as much as the count: "member X was dropped" without it sends an operator
        back to reading the graph by hand, which is the state E2 exists to end.
        """
        member = build_member()
        logger = logging.getLogger("test.clusters")

        with caplog.at_level(logging.INFO, logger="test.clusters"):
            build_cilium_peerings([member], logger=logger)

        assert len(caplog.records) == 1
        assert expected_reason in caplog.records[0].message

    @pytest.mark.parametrize("build_member", INELIGIBLE_BUILDERS)
    def test_the_log_line_names_the_omitted_member(
        self, build_member: Callable[[], NetworkServerService], caplog: pytest.LogCaptureFixture
    ) -> None:
        """The service name is the only handle an operator has back to the object they declared."""
        member = build_member()
        service_name = str(member.name.value)
        logger = logging.getLogger("test.clusters")

        with caplog.at_level(logging.INFO, logger="test.clusters"):
            build_cilium_peerings([member], logger=logger)

        assert service_name in caplog.records[0].message

    def test_an_eligible_member_logs_nothing(self, caplog: pytest.LogCaptureFixture) -> None:
        """A healthy cluster stays quiet, so every line in the log is a member worth looking at."""
        logger = logging.getLogger("test.clusters")

        with caplog.at_level(logging.INFO, logger="test.clusters"):
            build_cilium_peerings([_eligible_member()], logger=logger)

        assert caplog.records == []

    def test_without_a_logger_nothing_is_logged(self, caplog: pytest.LogCaptureFixture) -> None:
        """The module stays pure by default: no logger passed, no logger reached for."""
        with caplog.at_level(logging.INFO):
            build_cilium_peerings([_l2_member()])

        assert caplog.records == []

    def test_logging_changes_no_returned_record(self, caplog: pytest.LogCaptureFixture) -> None:
        """Passing a logger is observability only — the records, and so the artifact, are identical."""
        members = [_l2_member(), _eligible_member(), _member_without_server()]
        logger = logging.getLogger("test.clusters")

        with caplog.at_level(logging.INFO, logger="test.clusters"):
            with_logger = build_cilium_peerings(members, logger=logger)
        without_logger = build_cilium_peerings(members)

        assert with_logger == without_logger
        assert len(caplog.records) == 2
