"""Tests for ``ServerGenerator`` placement resolution (generators/generate_server.py).

Placement is the part of the generator that must be *stable across runs*: a ``NetworkServerService``
whose server is already cabled has to resolve to the same (rack, leaf, leaf port) on every re-run.
Recomputing it instead re-selected a different free port — the previously chosen one no longer counts
as free — and the second ``NetworkLink`` then broke the server port's cardinality-1 endpoint.

These exercise the async resolution paths with a recording fake client (no Infrahub, no network), so
the fall-through to selection and the reuse short-circuit are both pinned here rather than only in the
stack-gated integration test. The generator is built with ``__new__``: ``resolve_placement`` needs only
``client`` and the class-level ``logger``, and the real constructor would clone a client and read git.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple, cast

import pytest

from generators.generate_server import ServerGenerator

if TYPE_CHECKING:
    from collections.abc import Mapping

    from infrahub_sdk import InfrahubClient


class _Value(NamedTuple):
    """Stand-in for an Infrahub attribute leaf (exposes ``.value``)."""

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


class _RackStub:
    def __init__(self, rack_id: str, name: str) -> None:
        self.id = rack_id
        self.name = _Value(name)
        self.index = _Value(1)


class _LeafStub:
    def __init__(self, leaf_id: str, hostname: str, rack_id: str) -> None:
        self.id = leaf_id
        self.hostname = _Value(hostname)
        self.rack = _Related(rack_id)


class _LeafPortStub:
    def __init__(self, port_id: str, name: str, device_id: str, link_id: str | None = None) -> None:
        self.id = port_id
        self.name = _Value(name)
        self.role = _Value("server")
        self.ip_address = _Related()
        self.link = _Related(link_id)
        self.device = _Related(device_id)


class _ServerPortStub:
    def __init__(self, port_id: str, link_id: str | None) -> None:
        self.id = port_id
        self.name = _Value("eth1")
        self.link = _Related(link_id)


class _ServerStub:
    def __init__(self, server_id: str, hostname: str) -> None:
        self.id = server_id
        self.hostname = _Value(hostname)


class _LinkStub:
    def __init__(self, link_id: str, endpoint_ids: list[str]) -> None:
        self.id = link_id
        self.endpoints = _Peers([_Related(endpoint_id) for endpoint_id in endpoint_ids])


class _ServiceStub:
    """The subset of the parsed generator query ``resolve_placement`` reads."""

    def __init__(
        self,
        name: str = "cilium-worker-1",
        server_id: str | None = None,
        rack_id: str | None = None,
        leaf_port_id: str | None = None,
    ) -> None:
        self.id = "service-1"
        self.name = _Value(name)
        self.server = _Node(_Related(server_id)) if server_id else _Node()
        self.rack = _Node(_RackStub(rack_id, "Requested-Rack")) if rack_id else _Node()
        self.leaf_interface = _Node(_Related(leaf_port_id)) if leaf_port_id else _Node()


def _kind_name(kind: object) -> str:
    """Kinds reach the client either as a protocol class or as a plain string ("NetworkLink")."""
    return getattr(kind, "__name__", str(kind))


class _FakeClient:
    """Records every read so a test can assert what the generator did *not* need to look up."""

    def __init__(
        self,
        nodes: dict[str, object],
        ports_by_server: dict[str, list],
        servers_by_hostname: Mapping[str, object] | None = None,
    ) -> None:
        self.nodes = nodes
        self.ports_by_server = ports_by_server
        self.servers_by_hostname: Mapping[str, object] = servers_by_hostname or {}
        self.filter_kinds: list[str] = []
        self.get_kinds: list[str] = []
        self.get_ids: list[str] = []

    async def filters(self, kind: object, **kwargs: object) -> list:
        self.filter_kinds.append(_kind_name(kind))
        server_ids = kwargs.get("server__ids")
        if isinstance(server_ids, list) and server_ids:
            return self.ports_by_server.get(str(server_ids[0]), [])
        hostname = kwargs.get("hostname__value")
        if hostname is not None:
            server = self.servers_by_hostname.get(str(hostname))
            return [server] if server is not None else []
        return []

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
    server_port = _ServerPortStub("server-port-1", link_id="link-1")
    link = _LinkStub("link-1", [leaf_port.id, server_port.id])

    client = _FakeClient(
        nodes={
            rack.id: rack,
            leaf.id: leaf,
            leaf_port.id: leaf_port,
            link.id: link,
        },
        ports_by_server={"server-1": [server_port]},
        servers_by_hostname={"server-cilium-worker-1": _ServerStub("server-1", "server-cilium-worker-1")},
    )
    return client, rack, leaf, leaf_port


def _generator(client: _FakeClient) -> ServerGenerator:
    generator = ServerGenerator.__new__(ServerGenerator)
    generator.client = cast("InfrahubClient", client)
    return generator


class TestResolvePlacementIsIdempotent:
    async def test_reuses_the_placement_of_an_already_cabled_server(self) -> None:
        """A re-run resolves to the exact (rack, leaf, port) the first run cabled."""
        client, rack, leaf, leaf_port = _placed_graph()
        service = _ServiceStub(server_id="server-1")

        result_rack, result_leaf, result_port = await _generator(client).resolve_placement(
            cast("object", service),  # type: ignore[arg-type]
            fabric_id="fabric-1",
        )

        assert result_rack is rack
        assert result_leaf is leaf
        assert result_port is leaf_port

    async def test_reuse_never_reselects_a_rack_or_port(self) -> None:
        """The short-circuit must skip selection entirely — re-selecting is what picked a new port."""
        client, _, _, _ = _placed_graph()
        service = _ServiceStub(server_id="server-1")

        await _generator(client).resolve_placement(cast("object", service), fabric_id="fabric-1")  # type: ignore[arg-type]

        assert "NetworkPod" not in client.filter_kinds, "re-run re-selected a rack instead of reusing"
        assert "NetworkDevice" not in client.filter_kinds, "re-run re-selected a leaf port instead of reusing"

    async def test_rejects_an_explicit_request_that_contradicts_the_placement(self) -> None:
        """Re-pointing rack/leaf_interface on a cabled service fails loud, it is not silently ignored."""
        client, _, _, _ = _placed_graph()
        service = _ServiceStub(server_id="server-1", rack_id="rack-a3-1")

        with pytest.raises(ValueError, match="already placed"):
            await _generator(client).resolve_placement(cast("object", service), fabric_id="fabric-1")  # type: ignore[arg-type]

    async def test_unplaced_service_still_selects(self) -> None:
        """Without a server, resolution falls through to selection (here: no pods -> fail loud)."""
        client = _FakeClient(nodes={}, ports_by_server={})
        service = _ServiceStub()

        with pytest.raises(ValueError, match="no eligible rack"):
            await _generator(client).resolve_placement(cast("object", service), fabric_id="fabric-1")  # type: ignore[arg-type]

    async def test_reuses_a_cabled_server_the_service_never_recorded(self) -> None:
        """A run that died after cabling but before ``set_service_server`` must still be reused.

        ``generate`` cables at step 4 and only points ``service.server`` at step 6, so a failure in
        between (an exhausted ASN pool, an unallocated ``overlay_asn``) leaves a cabled server that the
        service does not reference. Keying reuse solely on that relationship would re-select a port and
        reproduce the original cardinality crash, so the deterministic hostname is the fallback.
        """
        client, rack, leaf, leaf_port = _placed_graph()
        service = _ServiceStub()  # no server relationship recorded

        result_rack, result_leaf, result_port = await _generator(client).resolve_placement(
            cast("object", service),  # type: ignore[arg-type]
            fabric_id="fabric-1",
        )

        assert result_rack is rack
        assert result_leaf is leaf
        assert result_port is leaf_port

    async def test_server_without_a_cabled_port_falls_through_to_selection(self) -> None:
        """A server whose eth1 has no link is only half-placed; selection must run to finish the job."""
        server_port = _ServerPortStub("server-port-1", link_id=None)
        client = _FakeClient(nodes={}, ports_by_server={"server-1": [server_port]})
        service = _ServiceStub(server_id="server-1")

        with pytest.raises(ValueError, match="no eligible rack"):
            await _generator(client).resolve_placement(cast("object", service), fabric_id="fabric-1")  # type: ignore[arg-type]
