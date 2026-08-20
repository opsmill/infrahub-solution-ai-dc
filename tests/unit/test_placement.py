"""Tests for server placement (src/infrahub_solution_ai_dc/placement.py).

Placement must be *stable across runs*: a ``NetworkServerService`` whose server is already cabled has
to resolve to the same (rack, leaf, leaf port) every time. Recomputing instead re-selected a different
free port — the previously chosen one no longer counts as free — and the second ``NetworkLink`` then
broke the server port's cardinality-1 endpoint.

That requirement got sharper once ``rack``/``leaf_interface`` became round-trip fields: the generator
writes the resolved placement back, so on every re-run the request *does* name an explicit rack and
port, and only the reuse short-circuit keeps those values from reaching the explicit path — where the
now-cabled port would fail its "must be free" check. Reuse-first is pinned here for that reason, as
are the two paths that deliberately do move a server: an operator re-pointing the service, and an
explicit port still holding this service's own leftovers.

These exercise the async resolution and teardown paths with a recording fake client (no Infrahub, no
network). Placement takes a :class:`PlacementRequest` of plain ids, so a test states the request
directly instead of building a parsed service node — reading one out of a query result is
``ServerGenerator.placement_request`` and is covered in tests/unit/test_server_generator.py.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, NamedTuple, cast

import pytest

from infrahub_solution_ai_dc.placement import PlacementRequest, ResolvedPlacement, ServerPlacement

if TYPE_CHECKING:
    from collections.abc import Mapping

    from infrahub_sdk import InfrahubClient

    from infrahub_solution_ai_dc.protocols import NetworkInterface


@dataclass
class _Value:
    """Stand-in for an Infrahub attribute leaf — mutable, since the generator writes ``status.value``."""

    value: object


class _Related(NamedTuple):
    """A to-one relationship pointing at ``id`` (``None`` when unset)."""

    id: str | None = None


class _Node(NamedTuple):
    """A to-one relationship wrapper exposing ``.node`` (the generator query's shape)."""

    node: object | None = None


class _Peers(NamedTuple):
    """A to-many relationship exposing ``.peers``."""

    peers: list


class _Recorded:
    """Base for stubs the generator may write to or delete.

    ``save`` snapshots the node's to-one relationship ids, because a real ``save`` re-sends whatever
    the node still holds — so *when* a relationship was cleared relative to the peer's deletion is
    behaviour worth asserting, not an implementation detail.
    """

    id: str
    _SNAPSHOT = ("ip_address", "link")

    def __init__(self) -> None:
        self.deleted = False
        self.save_count = 0
        self.saved_relationships: dict[str, str | None] = {}

    async def save(self, **_kwargs: object) -> None:
        self.save_count += 1
        self.saved_relationships = {
            field: getattr(getattr(self, field, None), "id", None) for field in self._SNAPSHOT if hasattr(self, field)
        }

    async def delete(self) -> None:
        self.deleted = True


class _RackStub(_Recorded):
    def __init__(self, rack_id: str, name: str) -> None:
        super().__init__()
        self.id = rack_id
        self.name = _Value(name)
        self.index = _Value(1)


class _LeafStub(_Recorded):
    def __init__(self, leaf_id: str, hostname: str, rack_id: str) -> None:
        super().__init__()
        self.id = leaf_id
        self.hostname = _Value(hostname)
        self.rack = _Related(rack_id)


class _LeafPortStub(_Recorded):
    def __init__(
        self,
        port_id: str,
        name: str,
        device_id: str,
        link_id: str | None = None,
        ip_id: str | None = None,
        role: str = "server",
    ) -> None:
        super().__init__()
        self.id = port_id
        self.name = _Value(name)
        self.role = _Value(role)
        self.status = _Value("active")
        self.ip_address = _Related(ip_id)
        self.link = _Related(link_id)
        self.device = _Related(device_id)


class _ServerPortStub(_Recorded):
    def __init__(self, port_id: str, link_id: str | None, server_id: str | None = None) -> None:
        super().__init__()
        self.id = port_id
        self.name = _Value("eth1")
        self.link = _Related(link_id)
        self.ip_address = _Related()
        self.server = _Related(server_id)


class _ServerStub(_Recorded):
    def __init__(self, server_id: str, hostname: str) -> None:
        super().__init__()
        self.id = server_id
        self.hostname = _Value(hostname)


class _LinkStub(_Recorded):
    def __init__(self, link_id: str, endpoint_ids: list[str], name: str = "a-link") -> None:
        super().__init__()
        self.id = link_id
        self.name = _Value(name)
        self.endpoints = _Peers([_Related(endpoint_id) for endpoint_id in endpoint_ids])


def _kind_name(kind: object) -> str:
    """Kinds reach the client either as a protocol class or as a plain string ("NetworkLink")."""
    return getattr(kind, "__name__", str(kind))


class _FakeClient:
    """Records every read so a test can assert what the generator did *not* need to look up.

    ``by_kind`` backs the id/device-scoped ``filters`` lookups (which endpoint a link reaches, which
    ports a leaf owns); ``nodes`` backs ``get`` by id.
    """

    def __init__(
        self,
        nodes: dict[str, object],
        ports_by_server: dict[str, list],
        servers_by_hostname: Mapping[str, object] | None = None,
        by_kind: Mapping[str, list] | None = None,
    ) -> None:
        self.nodes = nodes
        self.ports_by_server = ports_by_server
        self.servers_by_hostname: Mapping[str, object] = servers_by_hostname or {}
        self.by_kind: Mapping[str, list] = by_kind or {}
        self.filter_kinds: list[str] = []
        self.get_kinds: list[str] = []
        self.get_ids: list[str] = []

    async def filters(self, kind: object, **kwargs: object) -> list:
        name = _kind_name(kind)
        self.filter_kinds.append(name)

        server_ids = kwargs.get("server__ids")
        if isinstance(server_ids, list) and server_ids:
            return self.ports_by_server.get(str(server_ids[0]), [])
        hostname = kwargs.get("hostname__value")
        if hostname is not None:
            server = self.servers_by_hostname.get(str(hostname))
            return [server] if server is not None else []

        candidates = self.by_kind.get(name, [])
        for field, argument in (
            ("id", "ids"),
            ("device", "device__ids"),
            ("rack", "rack__ids"),
            ("peer_device", "peer_device__ids"),
        ):
            wanted = kwargs.get(argument)
            if not isinstance(wanted, list):
                continue
            candidates = [
                node
                for node in candidates
                if (node.id if field == "id" else getattr(getattr(node, field, None), "id", None)) in wanted
            ]
        return candidates

    async def get(self, kind: object, id: str | None = None, **_kwargs: object) -> object:  # noqa: A002
        self.get_kinds.append(_kind_name(kind))
        self.get_ids.append(str(id))
        return self.nodes[str(id)]


def _placed_graph() -> tuple[_FakeClient, _RackStub, _LeafStub, _LeafPortStub]:
    """A server already cabled: server eth1 -> link -> leaf port on a leaf in a rack.

    The server is reachable both ways a run can find it — by id (``service.server``) and by its
    deterministic hostname — so a test picks which path it exercises through the service stub.
    """
    rack = _RackStub("rack-a2-1", "Rack-A2-1")
    leaf = _LeafStub("leaf-1", "leaf-pod-a2-1-2", rack.id)
    leaf_port = _LeafPortStub("leaf-port-1", "Ethernet1/1", leaf.id, link_id="link-1")
    server_port = _ServerPortStub("server-port-1", link_id="link-1", server_id="server-1")
    link = _LinkStub("link-1", [leaf_port.id, server_port.id])
    server = _ServerStub("server-1", "server-cilium-worker-1")

    client = _FakeClient(
        nodes={
            rack.id: rack,
            leaf.id: leaf,
            leaf_port.id: leaf_port,
            link.id: link,
            server.id: server,
        },
        ports_by_server={"server-1": [server_port]},
        servers_by_hostname={"server-cilium-worker-1": server},
        by_kind={"ServerInterface": [server_port], "NetworkInterface": [leaf_port]},
    )
    return client, rack, leaf, leaf_port


def _placement(client: _FakeClient) -> ServerPlacement:
    return ServerPlacement(cast("InfrahubClient", client), logging.getLogger("test.placement"))


def _request(
    *,
    server_id: str | None = None,
    rack_id: str | None = None,
    leaf_port_id: str | None = None,
    hostname: str = "server-cilium-worker-1",
    fabric_id: str = "fabric-1",
) -> PlacementRequest:
    """The request a service produces once the generator has read it."""
    return PlacementRequest(
        fabric_id=fabric_id,
        server_hostname=hostname,
        linked_server_id=server_id,
        requested_rack_id=rack_id,
        requested_port_id=leaf_port_id,
    )


class TestResolvePlacementIsIdempotent:
    async def test_reuses_the_placement_of_an_already_cabled_server(self) -> None:
        """A re-run resolves to the exact (rack, leaf, port) the first run cabled."""
        client, rack, leaf, leaf_port = _placed_graph()
        request = _request(server_id="server-1")

        placement = await _placement(client).resolve(request)

        assert placement.rack is rack
        assert placement.leaf is leaf
        assert placement.leaf_port is leaf_port
        assert placement.released_ports == (), "an unchanged re-run must release nothing"

    async def test_reuses_the_placement_a_previous_run_wrote_back(self) -> None:
        """The realistic re-run: ``rack``/``leaf_interface`` hold the values ``record_placement`` wrote.

        Without the reuse short-circuit these would reach ``resolve_explicit_placement``, whose
        "port must be free" check the (now cabled) port cannot pass — so every re-run would fail loud.
        """
        client, rack, _, leaf_port = _placed_graph()
        request = _request(server_id="server-1", rack_id=rack.id, leaf_port_id=leaf_port.id)

        placement = await _placement(client).resolve(request)

        assert placement.leaf_port is leaf_port
        assert placement.released_ports == ()

    async def test_reuse_never_reselects_a_rack_or_port(self) -> None:
        """The short-circuit must skip selection entirely — re-selecting is what picked a new port."""
        client, _, _, _ = _placed_graph()
        request = _request(server_id="server-1")

        await _placement(client).resolve(request)

        assert "NetworkPod" not in client.filter_kinds, "re-run re-selected a rack instead of reusing"
        assert "NetworkDevice" not in client.filter_kinds, "re-run re-selected a leaf port instead of reusing"

    async def test_unplaced_service_still_selects(self) -> None:
        """Without a server, resolution falls through to selection (here: no pods -> fail loud)."""
        client = _FakeClient(nodes={}, ports_by_server={})
        request = _request()

        with pytest.raises(ValueError, match="no eligible rack"):
            await _placement(client).resolve(request)

    async def test_reuses_a_cabled_server_the_service_never_recorded(self) -> None:
        """A run that died after cabling but before ``record_placement`` must still be reused.

        ``generate`` cables at step 4 and only points ``service.server`` at step 7, so a failure in
        between (an exhausted ASN pool, an unallocated ``overlay_asn``) leaves a cabled server that the
        service does not reference. Keying reuse solely on that relationship would re-select a port and
        reproduce the original cardinality crash, so the deterministic hostname is the fallback.
        """
        client, rack, leaf, leaf_port = _placed_graph()
        request = _request()  # no server relationship recorded

        placement = await _placement(client).resolve(request)

        assert (placement.rack, placement.leaf, placement.leaf_port) == (rack, leaf, leaf_port)

    async def test_server_without_a_cabled_port_falls_through_to_selection(self) -> None:
        """A server whose eth1 has no link is only half-placed; selection must run to finish the job."""
        server_port = _ServerPortStub("server-port-1", link_id=None)
        client = _FakeClient(nodes={}, ports_by_server={"server-1": [server_port]})
        request = _request(server_id="server-1")

        with pytest.raises(ValueError, match="no eligible rack"):
            await _placement(client).resolve(request)


def _movable_graph() -> tuple[_FakeClient, _RackStub, _LeafPortStub, _RackStub, _LeafPortStub]:
    """The placed graph plus a second rack holding a free ``role:server`` port to move onto."""
    client, rack, leaf, leaf_port = _placed_graph()

    other_rack = _RackStub("rack-a3-1", "Rack-A3-1")
    other_leaf = _LeafStub("leaf-2", "leaf-pod-a3-1-1", other_rack.id)
    other_port = _LeafPortStub("leaf-port-2", "Ethernet1/1", other_leaf.id)

    client.nodes.update({other_rack.id: other_rack, other_leaf.id: other_leaf, other_port.id: other_port})
    client.by_kind = {
        **client.by_kind,
        "NetworkPod": [_RackStub("pod-1", "Pod-1")],
        "LocationRack": [rack, other_rack],
        "NetworkDevice": [leaf, other_leaf],
        "NetworkInterface": [leaf_port, other_port],
    }
    return client, rack, leaf_port, other_rack, other_port


class TestResolvePlacementRePlaces:
    """Editing ``rack``/``leaf_interface`` on a cabled service moves the server instead of failing."""

    async def test_a_moved_port_re_places_and_reports_the_old_port(self) -> None:
        """The new port is honored and the old one comes back to be released before re-cabling."""
        client, rack, leaf_port, _, other_port = _movable_graph()
        request = _request(server_id="server-1", rack_id=rack.id, leaf_port_id=other_port.id)

        placement = await _placement(client).resolve(request)

        assert placement.leaf_port is other_port
        assert placement.released_ports == (leaf_port,), "the superseded cable must be reported for teardown"

    async def test_a_moved_port_wins_over_the_written_back_rack(self) -> None:
        """Moving only the port must not be vetoed by the ``rack`` a previous run wrote back.

        The stale ``rack`` still names the rack being left behind, so honoring both would trip the
        port-on-a-leaf-of-the-rack check and make a cross-rack move by port impossible.
        """
        client, rack, _, other_rack, other_port = _movable_graph()
        request = _request(server_id="server-1", rack_id=rack.id, leaf_port_id=other_port.id)

        placement = await _placement(client).resolve(request)

        assert placement.rack is other_rack, "the rack must follow the port the operator moved to"

    async def test_a_moved_rack_picks_a_free_port_on_it(self) -> None:
        """Moving only the rack re-selects within it, ignoring the stale written-back port."""
        client, _, leaf_port, other_rack, other_port = _movable_graph()
        request = _request(server_id="server-1", rack_id=other_rack.id, leaf_port_id=leaf_port.id)

        placement = await _placement(client).resolve(request)

        assert placement.rack is other_rack
        assert placement.leaf_port is other_port
        assert placement.released_ports == (leaf_port,)


class TestPortIsReclaimable:
    """Whether an occupied explicit port holds only *this* service's leftovers (safe to tear down)."""

    def _client(self, *, server_ports: list, fabric_ports: list, nodes: dict) -> _FakeClient:
        return _FakeClient(
            nodes=nodes,
            ports_by_server={},
            by_kind={"ServerInterface": server_ports, "NetworkInterface": fabric_ports},
        )

    async def test_an_ip_without_a_cable_is_reclaimable(self) -> None:
        """Nothing is attached to a port with an address but no link — it is leftover by definition."""
        port = _LeafPortStub("leaf-port-1", "Ethernet5", "leaf-1", ip_id="ip-1")
        client = self._client(server_ports=[], fabric_ports=[], nodes={})

        assert (
            await _placement(client)._port_is_reclaimable(cast("NetworkInterface", port), "server-cilium-worker-1")
            is True
        )

    async def test_a_half_link_is_reclaimable(self) -> None:
        """A link whose far endpoint is gone is the trace a deleted server leaves behind."""
        port = _LeafPortStub("leaf-port-1", "Ethernet5", "leaf-1", link_id="link-1")
        link = _LinkStub("link-1", [port.id])
        client = self._client(server_ports=[], fabric_ports=[], nodes={link.id: link})

        assert (
            await _placement(client)._port_is_reclaimable(cast("NetworkInterface", port), "server-cilium-worker-1")
            is True
        )

    async def test_a_cable_to_our_own_server_is_reclaimable(self) -> None:
        """Our own cable may be torn down and re-laid; this is the manual-delete recovery path."""
        port = _LeafPortStub("leaf-port-1", "Ethernet5", "leaf-1", link_id="link-1")
        server_port = _ServerPortStub("server-port-1", link_id="link-1", server_id="server-1")
        link = _LinkStub("link-1", [port.id, server_port.id])
        server = _ServerStub("server-1", "server-cilium-worker-1")
        client = self._client(server_ports=[server_port], fabric_ports=[], nodes={link.id: link, server.id: server})

        assert (
            await _placement(client)._port_is_reclaimable(cast("NetworkInterface", port), "server-cilium-worker-1")
            is True
        )

    async def test_a_cable_to_another_server_is_not_reclaimable(self) -> None:
        """Never steal a port from a live server — this is what keeps the deletions safe."""
        port = _LeafPortStub("leaf-port-1", "Ethernet5", "leaf-1", link_id="link-1")
        server_port = _ServerPortStub("server-port-9", link_id="link-1", server_id="server-9")
        link = _LinkStub("link-1", [port.id, server_port.id])
        other = _ServerStub("server-9", "server-other-workload")
        client = self._client(server_ports=[server_port], fabric_ports=[], nodes={link.id: link, other.id: other})

        assert (
            await _placement(client)._port_is_reclaimable(cast("NetworkInterface", port), "server-cilium-worker-1")
            is False
        )

    async def test_a_fabric_cable_is_not_reclaimable(self) -> None:
        """A far end that is a switch port is fabric cabling, never a server's leftovers."""
        port = _LeafPortStub("leaf-port-1", "Ethernet5", "leaf-1", link_id="link-1")
        uplink = _LeafPortStub("leaf-port-9", "Ethernet49", "spine-1", link_id="link-1", role="uplink")
        link = _LinkStub("link-1", [port.id, uplink.id])
        client = self._client(server_ports=[], fabric_ports=[uplink], nodes={link.id: link})

        assert (
            await _placement(client)._port_is_reclaimable(cast("NetworkInterface", port), "server-cilium-worker-1")
            is False
        )

    async def test_a_multi_ended_link_is_not_reclaimable(self) -> None:
        """Several far ends is not a point-to-point server cable; refuse to guess rather than delete."""
        port = _LeafPortStub("leaf-port-1", "Ethernet5", "leaf-1", link_id="link-1")
        link = _LinkStub("link-1", [port.id, "other-a", "other-b"])
        client = self._client(server_ports=[], fabric_ports=[], nodes={link.id: link})

        assert (
            await _placement(client)._port_is_reclaimable(cast("NetworkInterface", port), "server-cilium-worker-1")
            is False
        )


class _AddressStub(_Recorded):
    def __init__(self, address_id: str, prefix_id: str | None) -> None:
        super().__init__()
        self.id = address_id
        self.address = _Value("10.0.0.1/31")
        self.ip_prefix = _Related(prefix_id)


class _PrefixStub(_Recorded):
    def __init__(self, prefix_id: str) -> None:
        super().__init__()
        self.id = prefix_id
        self.prefix = _Value("10.0.0.0/31")


class _SessionStub(_Recorded):
    def __init__(self, session_id: str, name: str, device_id: str, peer_device_id: str) -> None:
        super().__init__()
        self.id = session_id
        self.name = _Value(name)
        self.device = _Related(device_id)
        self.peer_device = _Related(peer_device_id)


class TestReleasePlacement:
    """The generator's only destructive step — tearing down the placement a move supersedes."""

    def _cabled(self, *, leaf_id: str = "leaf-1") -> tuple[_FakeClient, dict[str, _Recorded]]:
        """A fully-configured L3 attachment: cable, /31 on both ends, and the eBGP session pair."""
        leaf_port = _LeafPortStub("leaf-port-1", "Ethernet5", leaf_id, link_id="link-1", ip_id="ip-leaf")
        server_port = _ServerPortStub("server-port-1", link_id="link-1", server_id="server-1")
        server_port.ip_address = _Related("ip-server")
        link = _LinkStub("link-1", [leaf_port.id, server_port.id], name="leaf-1-Ethernet5__server-eth1")
        prefix = _PrefixStub("prefix-1")
        leaf_ip = _AddressStub("ip-leaf", prefix.id)
        server_ip = _AddressStub("ip-server", prefix.id)
        session_out = _SessionStub("session-1", "leaf-1__server-cilium-worker-1", leaf_id, "server-1")
        session_in = _SessionStub("session-2", "server-cilium-worker-1__leaf-1", "server-1", leaf_id)

        parts: dict[str, _Recorded] = {
            "leaf_port": leaf_port,
            "server_port": server_port,
            "link": link,
            "prefix": prefix,
            "leaf_ip": leaf_ip,
            "server_ip": server_ip,
            "session_out": session_out,
            "session_in": session_in,
        }
        client = _FakeClient(
            nodes={part.id: part for part in parts.values()},
            ports_by_server={},
            by_kind={"NetworkBGPSession": [session_out, session_in]},
        )
        return client, parts

    async def _release(
        self, client: _FakeClient, parts: dict[str, _Recorded], new_leaf_id: str, *, also: _Recorded | None = None
    ) -> None:
        """Release the cabled port (and optionally a second dirty one) onto a target on ``new_leaf_id``."""
        target_leaf = _LeafStub(new_leaf_id, "leaf-target", "rack-1")
        target_port = _LeafPortStub("leaf-port-target", "Ethernet9", new_leaf_id)
        released = (parts["leaf_port"], *((also,) if also is not None else ()))
        placement = ResolvedPlacement(
            cast("object", _RackStub("rack-1", "Rack-A")),  # type: ignore[arg-type]
            cast("object", target_leaf),  # type: ignore[arg-type]
            cast("object", target_port),  # type: ignore[arg-type]
            released_ports=cast("tuple", released),
        )
        await _placement(client).release(placement, server_id="server-1", server_port_id=parts["server_port"].id)

    async def test_deletes_the_cable_and_frees_the_port(self) -> None:
        """The old link goes, and the port returns to the inactive state the rack generator created it in."""
        client, parts = self._cabled()

        await self._release(client, parts, new_leaf_id="leaf-1")

        assert parts["link"].deleted
        assert parts["leaf_port"].status.value == "inactive"  # type: ignore[attr-defined]
        assert parts["leaf_port"].save_count == 1

    async def test_detaches_the_port_before_deleting_what_it_pointed_at(self) -> None:
        """Regression: the port's save must not still reference the cable and address being deleted.

        The port has to be saved anyway to go back to ``inactive``, and a save re-sends every
        relationship the node holds — so deleting first made that save fail against a real Infrahub
        with "Unable to find the node ... / IpamIPAddress in the database".
        """
        client, parts = self._cabled()

        await self._release(client, parts, new_leaf_id="leaf-1")

        assert parts["leaf_port"].saved_relationships == {"ip_address": None, "link": None}

    async def test_returns_the_whole_p2p_prefix_to_the_pool(self) -> None:
        """Both /31 ends *and* the prefix go — leaving it would leak one prefix per move."""
        client, parts = self._cabled()

        await self._release(client, parts, new_leaf_id="leaf-1")

        assert parts["leaf_ip"].deleted
        assert parts["server_ip"].deleted
        assert parts["prefix"].deleted

    async def test_keeps_the_sessions_when_the_server_stays_on_its_leaf(self) -> None:
        """A move between ports of one leaf leaves ``{device}__{peer}`` unchanged; upsert refreshes them."""
        client, parts = self._cabled()

        await self._release(client, parts, new_leaf_id="leaf-1")

        assert not parts["session_out"].deleted
        assert not parts["session_in"].deleted

    async def test_deletes_both_sessions_when_the_server_moves_to_another_leaf(self) -> None:
        """Otherwise the old pair survives and keeps rendering on the leaf the server just left."""
        client, parts = self._cabled()

        await self._release(client, parts, new_leaf_id="leaf-2")

        assert parts["session_out"].deleted
        assert parts["session_in"].deleted

    async def test_an_l2_release_has_no_prefix_to_free(self) -> None:
        """L2 attachments carry no /31, so the release is cable-only and must not fail looking for one."""
        client, parts = self._cabled()
        parts["leaf_port"].ip_address = _Related()  # type: ignore[attr-defined]
        parts["server_port"].ip_address = _Related()  # type: ignore[attr-defined]

        await self._release(client, parts, new_leaf_id="leaf-1")

        assert parts["link"].deleted
        assert not parts["prefix"].deleted

    async def test_a_dirty_target_port_is_emptied_too(self) -> None:
        """Moving onto a port that itself carried a stale address must not strand that address."""
        client, parts = self._cabled()
        stale_prefix = _PrefixStub("prefix-2")
        stale_ip = _AddressStub("ip-stale", stale_prefix.id)
        dirty_target = _LeafPortStub("leaf-port-target", "Ethernet9", "leaf-1", ip_id=stale_ip.id)
        client.nodes.update({part.id: part for part in (stale_prefix, stale_ip, dirty_target)})

        await self._release(client, parts, new_leaf_id="leaf-1", also=dirty_target)

        assert stale_ip.deleted
        assert stale_prefix.deleted
        assert dirty_target.status.value == "inactive"
