"""Tests for the Server-service helpers (src/infrahub_solution_ai_dc/servers.py) — US1 unit tests.

These exercise the *pure* placement helpers with plain stubs (no Infrahub client, no network),
mirroring tests/unit/test_overlay.py, plus the directional eBGP upsert with a recording fake client.

Fail-loud note: ``select_least_utilized_rack`` and ``select_free_server_port`` are non-raising —
they return ``None`` when nothing is eligible. The actual raising (``ValueError``) for the
no-eligible-rack, no-free-port and pool-exhaustion paths lives in the async ``ServerGenerator``
(``select_rack`` / ``select_leaf_port`` / ``allocate_server_asn``), which needs a client and so is
covered by the integration test, not here. These tests pin the ``None`` precondition that the
generator turns into a fail-loud error.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, NamedTuple, cast

import pytest

from infrahub_solution_ai_dc.servers import (
    peer_endpoint_id,
    require_allocated,
    select_free_server_port,
    select_least_utilized_rack,
    upsert_ebgp_session,
    validate_explicit_port,
    validate_placement_matches_request,
    validate_service,
)

if TYPE_CHECKING:
    from infrahub_sdk import InfrahubClient

    from infrahub_solution_ai_dc.protocols import LocationRack, NetworkBGPPeer, NetworkInterface

_LOGGER = logging.getLogger("test.servers")


class _Value(NamedTuple):
    """Stand-in for an Infrahub attribute leaf (exposes ``.value``)."""

    value: object


class _Related(NamedTuple):
    """A *set* to-one relationship — a related node carrying a non-null ``id``."""

    id: str = "set"


class _RackStub:
    """Minimal LocationRack stub: only the fields ``select_least_utilized_rack`` reads."""

    def __init__(self, rack_id: str, index: int, name: str) -> None:
        self.id = rack_id
        self.index = _Value(index)
        self.name = _Value(name)


class _InterfaceStub:
    """Minimal NetworkInterface stub: name/role, its owning device, + the relationships checked for 'free'."""

    def __init__(
        self,
        name: str,
        role: str = "server",
        ip_address: _Related | None = None,
        link: _Related | None = None,
        device_id: str = "leaf",
    ) -> None:
        self.name = _Value(name)
        self.role = _Value(role)
        self.ip_address = ip_address
        self.link = link
        self.device = _Related(device_id)


def _rack(rack_id: str, index: int, name: str) -> LocationRack:
    return cast("LocationRack", _RackStub(rack_id, index, name))


def _interface(
    name: str,
    role: str = "server",
    ip_address: _Related | None = None,
    link: _Related | None = None,
    device_id: str = "leaf",
) -> NetworkInterface:
    return cast("NetworkInterface", _InterfaceStub(name, role, ip_address, link, device_id))


class TestSelectLeastUtilizedRack:
    def test_returns_rack_with_fewest_servers(self) -> None:
        """The eligible rack hosting the fewest servers wins."""
        busy = _rack("r-busy", index=1, name="Rack-A")
        idle = _rack("r-idle", index=2, name="Rack-B")

        result = select_least_utilized_rack([busy, idle], {"r-busy": 3, "r-idle": 1})

        assert result is idle

    def test_missing_from_counts_is_zero(self) -> None:
        """A rack absent from the counts mapping is treated as hosting zero servers."""
        counted = _rack("r-counted", index=1, name="Rack-A")
        uncounted = _rack("r-uncounted", index=2, name="Rack-B")

        result = select_least_utilized_rack([counted, uncounted], {"r-counted": 1})

        assert result is uncounted

    def test_tie_break_by_index_then_name(self) -> None:
        """Equal utilization is broken deterministically by rack index, then name."""
        low_index = _rack("r-1", index=1, name="Rack-Z")
        high_index = _rack("r-2", index=2, name="Rack-A")

        result = select_least_utilized_rack([high_index, low_index], {})

        assert result is low_index

    def test_tie_break_is_stable_regardless_of_input_order(self) -> None:
        """The same set of tied racks yields the same winner no matter the input ordering."""
        a = _rack("r-a", index=5, name="Rack-A")
        b = _rack("r-b", index=5, name="Rack-B")

        forward = select_least_utilized_rack([a, b], {})
        reverse = select_least_utilized_rack([b, a], {})

        assert forward is a
        assert reverse is a

    def test_empty_racks_returns_none(self) -> None:
        """No eligible rack -> None (the ServerGenerator turns this into a fail-loud ValueError)."""
        assert select_least_utilized_rack([], {}) is None

    def test_repeated_placement_spreads_evenly(self) -> None:
        """SC-005: placing N servers one at a time keeps the racks balanced within one server.

        This drives the placement loop the ServerGenerator performs across successive service
        materializations: each call picks the current least-utilized rack, and that rack's count is
        then incremented. After every placement the spread (max - min server count across racks) must
        stay <= 1, proving the even-spread success criterion.
        """
        racks = [
            _rack("r-1", index=1, name="Rack-A"),
            _rack("r-2", index=2, name="Rack-B"),
            _rack("r-3", index=3, name="Rack-C"),
        ]
        counts: dict[str, int] = {}

        for _ in range(10):
            winner = select_least_utilized_rack(racks, counts)
            assert winner is not None
            counts[winner.id] = counts.get(winner.id, 0) + 1
            # After each placement, every rack (incl. the ones never chosen yet -> 0) stays balanced.
            per_rack = [counts.get(rack.id, 0) for rack in racks]
            assert max(per_rack) - min(per_rack) <= 1

        assert sum(counts.values()) == 10


class TestSelectFreeServerPort:
    def test_returns_lowest_numbered_free_port(self) -> None:
        """Among free role:server ports the lowest-numbered (netutils order) is chosen."""
        high = _interface("Ethernet10")
        low = _interface("Ethernet2")

        result = select_free_server_port([high, low])

        assert result is low

    def test_ignores_non_server_roles(self) -> None:
        """A free but wrong-role interface is never selected."""
        uplink = _interface("Ethernet1", role="uplink")
        server = _interface("Ethernet2", role="server")

        result = select_free_server_port([uplink, server])

        assert result is server

    def test_ignores_ports_with_ip_address(self) -> None:
        """A role:server port that already carries an IP address is not free."""
        used = _interface("Ethernet1", ip_address=_Related())
        free = _interface("Ethernet2")

        result = select_free_server_port([used, free])

        assert result is free

    def test_ignores_cabled_ports(self) -> None:
        """A role:server port already cabled (link set) is not free."""
        cabled = _interface("Ethernet1", link=_Related())
        free = _interface("Ethernet2")

        result = select_free_server_port([cabled, free])

        assert result is free

    def test_no_free_port_returns_none(self) -> None:
        """No free role:server port -> None (the ServerGenerator turns this into a fail-loud ValueError)."""
        occupied = _interface("Ethernet1", ip_address=_Related(), link=_Related())
        wrong_role = _interface("Ethernet2", role="uplink")

        assert select_free_server_port([occupied, wrong_role]) is None

    def test_empty_interfaces_returns_none(self) -> None:
        """An empty candidate set yields None."""
        assert select_free_server_port([]) is None

    def test_same_named_ports_on_two_leaves_break_the_tie_by_device(self) -> None:
        """A rack's leaves share port names, so the tie must break on the device — not on query order.

        ``select_leaf_port`` feeds this the free ports of *every* leaf in the rack, so two leaves both
        offering ``Ethernet1/1`` are ordinary. Keying candidates by name alone made the winner depend
        on iteration order, so consecutive runs could pick a different leaf for the same rack.
        """
        on_leaf_b = _interface("Ethernet1/1", device_id="leaf-b")
        on_leaf_a = _interface("Ethernet1/1", device_id="leaf-a")

        assert select_free_server_port([on_leaf_b, on_leaf_a]) is on_leaf_a
        assert select_free_server_port([on_leaf_a, on_leaf_b]) is on_leaf_a

    def test_lowest_name_still_wins_across_devices(self) -> None:
        """Port ordering is by interface name first; the device only breaks an exact-name tie."""
        high_on_first_leaf = _interface("Ethernet10", device_id="leaf-a")
        low_on_second_leaf = _interface("Ethernet2", device_id="leaf-b")

        result = select_free_server_port([high_on_first_leaf, low_on_second_leaf])

        assert result is low_on_second_leaf


class TestPeerEndpointId:
    """Resolving the far end of a two-ended ``NetworkLink`` (the leaf port behind a server port)."""

    def test_returns_the_other_end_of_the_link(self) -> None:
        """Given both endpoint ids and our own, the remaining one is the peer."""
        assert peer_endpoint_id(["leaf-port", "server-port"], "server-port") == "leaf-port"

    def test_returns_none_when_link_has_no_other_end(self) -> None:
        """A half-built link (only our own endpoint) has no peer to reuse."""
        assert peer_endpoint_id(["server-port"], "server-port") is None

    def test_returns_none_when_the_peer_is_ambiguous(self) -> None:
        """More than one far end is not a point-to-point link; refuse to guess."""
        assert peer_endpoint_id(["leaf-a-port", "leaf-b-port", "server-port"], "server-port") is None


class TestValidatePlacementMatchesRequest:
    """An already-placed service may only be reused when the request still asks for that placement."""

    def test_accepts_reuse_when_the_request_names_nothing(self) -> None:
        """Automatic placement: nothing requested, so the existing placement stands."""
        validate_placement_matches_request(
            "cilium-worker-1", placed_rack_id="rack-1", placed_port_id="port-1",
            requested_rack_id=None, requested_port_id=None,
        )

    def test_accepts_reuse_when_the_request_matches(self) -> None:
        """An explicit request identical to what was already materialized is a no-op."""
        validate_placement_matches_request(
            "cilium-worker-1", placed_rack_id="rack-1", placed_port_id="port-1",
            requested_rack_id="rack-1", requested_port_id="port-1",
        )

    def test_rejects_a_rack_change_on_a_placed_service(self) -> None:
        """Re-placing a cabled server is not supported; fail loud instead of silently ignoring the request."""
        with pytest.raises(ValueError, match="already placed"):
            validate_placement_matches_request(
                "cilium-worker-1", placed_rack_id="rack-1", placed_port_id="port-1",
                requested_rack_id="rack-2", requested_port_id=None,
            )

    def test_rejects_a_port_change_on_a_placed_service(self) -> None:
        """Same for a new explicit leaf_interface on an already-cabled service."""
        with pytest.raises(ValueError, match="already placed"):
            validate_placement_matches_request(
                "cilium-worker-1", placed_rack_id="rack-1", placed_port_id="port-1",
                requested_rack_id=None, requested_port_id="port-2",
            )


class _RecordedSession:
    """Captures the kwargs a NetworkBGPSession was created with; records save() calls."""

    def __init__(self, name: str) -> None:
        self.name = _Value(name)
        self.saved_with: dict | None = None

    async def save(self, **kwargs: object) -> None:
        self.saved_with = kwargs


class _RecordingClient:
    """A minimal async stand-in for InfrahubClient that records create() calls (no network)."""

    def __init__(self) -> None:
        self.created: list[dict] = []
        self.sessions: list[_RecordedSession] = []

    async def create(self, **kwargs: object) -> _RecordedSession:
        self.created.append(kwargs)
        session = _RecordedSession(str(kwargs["name"]))
        self.sessions.append(session)
        return session


class _PeerStub:
    """A BGP peer stub carrying the ``id`` + ``hostname.value`` upsert_ebgp_session reads."""

    def __init__(self, peer_id: str, hostname: str) -> None:
        self.id = peer_id
        self.hostname = _Value(hostname)


def _peer(peer_id: str, hostname: str) -> NetworkBGPPeer:
    return cast("NetworkBGPPeer", _PeerStub(peer_id, hostname))


class TestUpsertEbgpSession:
    async def test_session_shape_is_ipv4_unicast_non_rr(self) -> None:
        """A single directional session is ipv4_unicast, non-RR, named ``<device>__<peer>``, upserted."""
        client = _RecordingClient()
        leaf = _peer("leaf-id", "leaf-a1")
        server = _peer("server-id", "server-cilium-worker-1")

        await upsert_ebgp_session(
            cast("InfrahubClient", client),
            _LOGGER,
            device=leaf,
            peer=server,
            local_as=65000,
            remote_as=4200000001,
        )

        (created,) = client.created
        assert created["name"] == "leaf-a1__server-cilium-worker-1"
        assert created["device"] == {"id": "leaf-id"}
        assert created["peer_device"] == {"id": "server-id"}
        assert created["address_family"] == "ipv4_unicast"
        assert created["rr_client"] is False
        assert client.sessions[0].saved_with == {"allow_upsert": True}

    async def test_ebgp_pairing_swaps_local_and_remote_as(self) -> None:
        """The leaf<->server pair carries mirrored AS: each side's remote_as is the other's local_as."""
        client = _RecordingClient()
        leaf = _peer("leaf-id", "leaf-a1")
        server = _peer("server-id", "server-cilium-worker-1")
        overlay_asn = 65000
        server_asn = 4200000001

        # Mirrors ServerGenerator.configure_l3: leaf peers the server ASN; server peers the fabric ASN.
        await upsert_ebgp_session(
            cast("InfrahubClient", client),
            _LOGGER,
            device=leaf,
            peer=server,
            local_as=overlay_asn,
            remote_as=server_asn,
        )
        await upsert_ebgp_session(
            cast("InfrahubClient", client),
            _LOGGER,
            device=server,
            peer=leaf,
            local_as=server_asn,
            remote_as=overlay_asn,
        )

        leaf_side, server_side = client.created
        # Leaf side: local = fabric overlay ASN, remote = server ASN.
        assert leaf_side["name"] == "leaf-a1__server-cilium-worker-1"
        assert leaf_side["local_as"] == overlay_asn
        assert leaf_side["remote_as"] == server_asn
        # Server side: local = server ASN, remote = fabric overlay ASN (mirrored).
        assert server_side["name"] == "server-cilium-worker-1__leaf-a1"
        assert server_side["local_as"] == server_asn
        assert server_side["remote_as"] == overlay_asn


class TestValidateService:
    """Fail-loud L2/L3 intent validation (pure, synchronous — the generator calls it before any write)."""

    def test_l3_without_segment_is_valid(self) -> None:
        """An L3 service naming no segment is the normal case: no raise."""
        validate_service("l3", "cilium-worker-1", "vrf-blue", segment_id=None, segment_vrf_id=None)

    def test_l2_with_segment_in_same_vrf_is_valid(self) -> None:
        """An L2 service whose segment is in the service's VRF is valid: no raise."""
        validate_service("l2", "web-host-1", "vrf-blue", segment_id="seg-l2", segment_vrf_id="vrf-blue")

    def test_l2_without_segment_fails_loud(self) -> None:
        """L2 requires a segment; omitting it raises, naming the offending service (no partial objects)."""
        with pytest.raises(ValueError, match=r"web-host-1.*L2.*segment"):
            validate_service("l2", "web-host-1", "vrf-blue", segment_id=None, segment_vrf_id=None)

    def test_l2_segment_in_other_vrf_fails_loud(self) -> None:
        """L2 with a segment belonging to a different VRF than the service raises (segment.vrf != service.vrf)."""
        with pytest.raises(ValueError, match="not the service's VRF"):
            validate_service("l2", "web-host-1", "vrf-blue", segment_id="seg-l2", segment_vrf_id="vrf-red")

    def test_l3_with_segment_is_contradictory_and_fails_loud(self) -> None:
        """An L3 service that also names a segment is a contradictory request and raises."""
        with pytest.raises(ValueError, match="contradictory"):
            validate_service("l3", "cilium-worker-1", "vrf-blue", segment_id="seg-l2", segment_vrf_id="vrf-blue")


class TestValidateExplicitPort:
    """Fail-loud validation of an explicitly-requested leaf port (US3, pure — no client needed).

    The rack∈fabric and port-on-a-leaf-of-the-rack checks are async graph reads in the
    ``ServerGenerator`` (``resolve_explicit_placement``); the role + free checks are pure and pinned
    here. ``rack_name`` is used only for the error message.
    """

    def test_free_server_port_is_honored(self) -> None:
        """A free ``role:server`` port passes validation (no raise) — the honor case."""
        port = _interface("Ethernet5", role="server")

        validate_explicit_port(port, "Rack-A")  # must not raise

    def test_occupied_cabled_port_fails_loud(self) -> None:
        """A ``role:server`` port already cabled (link set) is rejected, naming the port."""
        port = _interface("Ethernet5", role="server", link=_Related())

        with pytest.raises(ValueError, match=r"Ethernet5.*already in use"):
            validate_explicit_port(port, "Rack-A")

    def test_port_with_ip_address_fails_loud(self) -> None:
        """A ``role:server`` port that already carries an IP address is rejected."""
        port = _interface("Ethernet5", role="server", ip_address=_Related())

        with pytest.raises(ValueError, match="already in use"):
            validate_explicit_port(port, "Rack-A")

    def test_wrong_role_port_fails_loud(self) -> None:
        """A free but wrong-role port is rejected, reporting the offending role."""
        port = _interface("Ethernet5", role="uplink")

        with pytest.raises(ValueError, match=r"role.*not 'server'"):
            validate_explicit_port(port, "Rack-A")


class TestRequireAllocated:
    """Pure pool-exhaustion guard (the fail-loud path the ServerGenerator uses for pool allocation)."""

    def test_none_fails_loud_naming_the_pool(self) -> None:
        """A ``None`` allocation (exhausted/misnamed pool) raises, naming the offending pool."""
        with pytest.raises(ValueError, match="Server ASN Pool"):
            require_allocated(None, "Server ASN Pool")

    def test_value_passes_through_unchanged(self) -> None:
        """A real allocated value is returned unchanged (the normal case)."""
        assert require_allocated(4200000001, "Server ASN Pool") == 4200000001
