"""Tests for ``ServerGenerator`` (generators/generate_server.py).

What is left here is what the generator itself owns once placement moved out
(src/infrahub_solution_ai_dc/placement.py, tests/unit/test_placement.py): reading a
:class:`~infrahub_solution_ai_dc.placement.PlacementRequest` out of the parsed query result, and
writing the resolved placement back onto the service.

The generator is built with ``__new__``: these paths need only ``client`` and the class-level
``logger``, and the real constructor would clone a client and read git.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, NamedTuple, cast

from generators.generate_server import ServerGenerator

if TYPE_CHECKING:
    from collections.abc import Mapping

    from infrahub_sdk import InfrahubClient

    from generators.generate_server_query import ServerGeneratorQueryServiceNode
    from infrahub_solution_ai_dc.placement import PlacementRequest


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


class _ServiceStub(_Recorded):
    """The subset of the parsed generator query ``resolve_placement`` reads."""

    def __init__(
        self,
        name: str = "cilium-worker-1",
        server_id: str | None = None,
        rack_id: str | None = None,
        leaf_port_id: str | None = None,
    ) -> None:
        super().__init__()
        self.id = "service-1"
        self.name = _Value(name)
        self.server = _Node(_Related(server_id)) if server_id else _Node()
        self.rack = _Node(_Related(rack_id)) if rack_id else _Node()
        self.leaf_interface = _Node(_Related(leaf_port_id)) if leaf_port_id else _Node()


class _ServiceRecordStub(_Recorded):
    """The service as ``record_placement`` sees it — a node whose to-one relationships it assigns onto.

    Assigning ``{"id": ...}`` to a relationship is how the SDK's ``InfrahubNode`` takes a new peer, so
    the stub resolves that back to a ``.id``-bearing object the way a real node would.
    """

    _RELATIONSHIPS = ("server", "rack", "leaf_interface")

    def __init__(
        self, server_id: str | None = None, rack_id: str | None = None, leaf_port_id: str | None = None
    ) -> None:
        super().__init__()
        self.id = "service-1"
        self.server = _Related(server_id)
        self.rack = _Related(rack_id)
        self.leaf_interface = _Related(leaf_port_id)

    def __setattr__(self, name: str, value: object) -> None:
        if name in self._RELATIONSHIPS and isinstance(value, dict):
            value = _Related(str(value["id"]))
        super().__setattr__(name, value)


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


def _generator(client: _FakeClient) -> ServerGenerator:
    generator = ServerGenerator.__new__(ServerGenerator)
    generator.client = cast("InfrahubClient", client)
    return generator


class TestRecordPlacement:
    """The write-back that stops ``rack``/``leaf_interface`` from staying empty after an auto-placement."""

    async def test_writes_back_an_automatically_resolved_placement(self) -> None:
        """The reported bug: an auto-placed service must end up naming its rack and leaf port."""
        service = _ServiceRecordStub()
        client = _FakeClient(nodes={service.id: service}, ports_by_server={})

        await _generator(client).record_placement(service.id, "server-1", "rack-a2-1", "leaf-port-1")

        assert service.server.id == "server-1"
        assert service.rack.id == "rack-a2-1"
        assert service.leaf_interface.id == "leaf-port-1"
        assert service.save_count == 1, "the three fields must share one save"

    async def test_an_unchanged_re_run_writes_nothing(self) -> None:
        """Every service is processed at least twice; the second pass must produce an empty diff."""
        service = _ServiceRecordStub(server_id="server-1", rack_id="rack-a2-1", leaf_port_id="leaf-port-1")
        client = _FakeClient(nodes={service.id: service}, ports_by_server={})

        await _generator(client).record_placement(service.id, "server-1", "rack-a2-1", "leaf-port-1")

        assert service.save_count == 0

    async def test_a_move_rewrites_only_what_changed(self) -> None:
        """After a re-placement the service names the new port, and still saves once."""
        service = _ServiceRecordStub(server_id="server-1", rack_id="rack-a2-1", leaf_port_id="leaf-port-1")
        client = _FakeClient(nodes={service.id: service}, ports_by_server={})

        await _generator(client).record_placement(service.id, "server-1", "rack-a2-1", "leaf-port-2")

        assert service.leaf_interface.id == "leaf-port-2"
        assert service.rack.id == "rack-a2-1"
        assert service.save_count == 1


class TestPlacementRequest:
    """Reading the parsed service node into the plain ids placement decides on."""

    def _request(self, service: _ServiceStub) -> PlacementRequest:
        return ServerGenerator.placement_request(cast("ServerGeneratorQueryServiceNode", service), "fabric-1")

    def test_the_hostname_is_derived_from_the_service_name(self) -> None:
        """Placement finds an already-cabled server by this name when the relationship is unset."""
        assert self._request(_ServiceStub(name="cilium-worker-1")).server_hostname == "server-cilium-worker-1"

    def test_a_linked_server_is_passed_through(self) -> None:
        assert self._request(_ServiceStub(server_id="server-1")).linked_server_id == "server-1"

    def test_an_unlinked_service_reports_no_server(self) -> None:
        """A service the generator has not reached yet; placement falls back to the hostname lookup."""
        assert self._request(_ServiceStub()).linked_server_id is None

    def test_the_round_trip_fields_are_passed_through_as_ids(self) -> None:
        """``rack``/``leaf_interface`` reach placement exactly as found, request or write-back alike."""
        request = self._request(_ServiceStub(rack_id="rack-a2-1", leaf_port_id="leaf-port-1"))

        assert request.requested_rack_id == "rack-a2-1"
        assert request.requested_port_id == "leaf-port-1"

    def test_unset_round_trip_fields_are_absent(self) -> None:
        """The automatic path: nothing requested, so placement selects."""
        request = self._request(_ServiceStub())

        assert request.requested_rack_id is None
        assert request.requested_port_id is None

    def test_the_fabric_id_is_carried(self) -> None:
        assert self._request(_ServiceStub()).fabric_id == "fabric-1"
