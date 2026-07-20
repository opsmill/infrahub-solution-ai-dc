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

from infrahub_solution_ai_dc.servers import (
    select_free_server_port,
    select_least_utilized_rack,
    upsert_ebgp_session,
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
    """Minimal NetworkInterface stub: name/role + the two to-one relationships checked for 'free'."""

    def __init__(
        self,
        name: str,
        role: str = "server",
        ip_address: _Related | None = None,
        link: _Related | None = None,
    ) -> None:
        self.name = _Value(name)
        self.role = _Value(role)
        self.ip_address = ip_address
        self.link = link


def _rack(rack_id: str, index: int, name: str) -> LocationRack:
    return cast("LocationRack", _RackStub(rack_id, index, name))


def _interface(
    name: str,
    role: str = "server",
    ip_address: _Related | None = None,
    link: _Related | None = None,
) -> NetworkInterface:
    return cast("NetworkInterface", _InterfaceStub(name, role, ip_address, link))


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
