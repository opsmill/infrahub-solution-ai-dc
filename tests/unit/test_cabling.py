"""Tests for cabling plan algorithms."""

import logging
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, PropertyMock

from infrahub_solution_ai_dc.cabling import (
    build_pod_cabling_plan,
    build_rack_cabling_plan,
    connect_interface_maps,
)


def _make_device(index: int = 1) -> MagicMock:
    """Create a mock NetworkDevice."""
    dev = MagicMock()
    type(dev.index).value = PropertyMock(return_value=index)
    return dev


def _make_interface(name: str = "Ethernet1") -> MagicMock:
    """Create a mock NetworkInterface."""
    intf = MagicMock()
    type(intf.name).value = PropertyMock(return_value=name)
    return intf


class TestBuildPodCablingPlan:
    def test_basic_cabling(self) -> None:
        """Test a simple 2-src x 2-dst cabling plan."""
        src_dev1 = _make_device(1)
        src_dev2 = _make_device(2)
        dst_dev1 = _make_device(1)
        dst_dev2 = _make_device(2)

        src_intf1_1 = _make_interface("Ethernet1")
        src_intf1_2 = _make_interface("Ethernet2")
        src_intf2_1 = _make_interface("Ethernet1")
        src_intf2_2 = _make_interface("Ethernet2")

        # Each dst device needs enough interfaces for the pod_index offset
        dst_intfs1 = [_make_interface(f"Ethernet{i}") for i in range(10)]
        dst_intfs2 = [_make_interface(f"Ethernet{i}") for i in range(10)]

        src_map: dict[Any, Any] = {
            src_dev1: [src_intf1_1, src_intf1_2],
            src_dev2: [src_intf2_1, src_intf2_2],
        }
        dst_map: dict[Any, Any] = {
            dst_dev1: dst_intfs1,
            dst_dev2: dst_intfs2,
        }

        result = build_pod_cabling_plan(pod_index=2, src_interface_map=src_map, dst_interface_map=dst_map)

        assert len(result) == 4
        # All entries should be (src_interface, dst_interface) tuples
        for src, dst in result:
            assert src is not None
            assert dst is not None

    def test_empty_maps(self) -> None:
        result = build_pod_cabling_plan(pod_index=2, src_interface_map={}, dst_interface_map={})
        assert result == []


class TestBuildRackCablingPlan:
    def test_basic_rack_cabling(self) -> None:
        """Test a simple rack cabling plan with 2 src devices and 2 dst devices."""
        src_dev1 = _make_device(1)
        src_dev2 = _make_device(2)
        dst_dev1 = _make_device(1)
        dst_dev2 = _make_device(2)

        src_intf1_1 = _make_interface("Ethernet1")
        src_intf1_2 = _make_interface("Ethernet2")
        src_intf2_1 = _make_interface("Ethernet1")
        src_intf2_2 = _make_interface("Ethernet2")

        # Each dst device needs enough interfaces for indexing: (rack_index * 2)
        dst_intfs1 = [_make_interface(f"Ethernet{i}") for i in range(10)]
        dst_intfs2 = [_make_interface(f"Ethernet{i}") for i in range(10)]

        src_map: dict[Any, Any] = {
            src_dev1: [src_intf1_1, src_intf1_2],
            src_dev2: [src_intf2_1, src_intf2_2],
        }
        dst_map: dict[Any, Any] = {
            dst_dev1: dst_intfs1,
            dst_dev2: dst_intfs2,
        }

        result = build_rack_cabling_plan(rack_index=1, src_interface_map=src_map, dst_interface_map=dst_map)

        assert len(result) == 4
        for src, dst in result:
            assert src is not None
            assert dst is not None

    def test_empty_maps(self) -> None:
        result = build_rack_cabling_plan(rack_index=1, src_interface_map={}, dst_interface_map={})
        assert result == []


def _cabled_interface(intf_id: str, device_label: str, name: str) -> MagicMock:
    intf = MagicMock()
    intf.id = intf_id
    intf.device.display_label = device_label
    intf.name.value = name
    return intf


def _existing_link(name: str, endpoint_ids: list[str]) -> MagicMock:
    link = MagicMock()
    link.name.value = name
    link.endpoints.peers = [SimpleNamespace(id=endpoint_id) for endpoint_id in endpoint_ids]
    link.save = AsyncMock()
    return link


def _client(existing_links: list[MagicMock]) -> MagicMock:
    client = MagicMock()
    client.filters = AsyncMock(return_value=existing_links)
    client.create = AsyncMock(return_value=SimpleNamespace(save=AsyncMock()))
    client.get = AsyncMock(
        side_effect=lambda *_args, **_kwargs: SimpleNamespace(status=SimpleNamespace(value=None), save=AsyncMock())
    )
    return client


class TestConnectInterfaceMaps:
    """Re-running a generator keeps the links it created, even after a device rename (issue #120)."""

    async def test_creates_a_link_when_none_exists(self) -> None:
        client = _client(existing_links=[])
        src = _cabled_interface("src", "leaf-1", "Ethernet1")
        dst = _cabled_interface("dst", "spine-1", "Ethernet3")

        await connect_interface_maps(client, logging.getLogger(__name__), [(src, dst)])

        client.create.assert_awaited_once()
        assert client.create.await_args.kwargs["name"] == "leaf-1-Ethernet1__spine-1-Ethernet3"

    async def test_reuses_and_renames_the_link_after_a_device_rename(self) -> None:
        link = _existing_link("leaf-1-Ethernet1__old-spine-Ethernet3", ["src", "dst"])
        client = _client(existing_links=[link])
        src = _cabled_interface("src", "leaf-1", "Ethernet1")
        dst = _cabled_interface("dst", "new-spine", "Ethernet3")

        await connect_interface_maps(client, logging.getLogger(__name__), [(src, dst)])

        client.create.assert_not_awaited()
        assert link.name.value == "leaf-1-Ethernet1__new-spine-Ethernet3"
        link.save.assert_awaited_once()

    async def test_still_saves_an_unchanged_link_so_the_generator_group_tracks_it(self) -> None:
        link = _existing_link("leaf-1-Ethernet1__spine-1-Ethernet3", ["dst", "src"])
        client = _client(existing_links=[link])
        src = _cabled_interface("src", "leaf-1", "Ethernet1")
        dst = _cabled_interface("dst", "spine-1", "Ethernet3")

        await connect_interface_maps(client, logging.getLogger(__name__), [(src, dst)])

        client.create.assert_not_awaited()
        assert link.name.value == "leaf-1-Ethernet1__spine-1-Ethernet3"
        link.save.assert_awaited_once()

    async def test_ignores_a_link_to_another_interface(self) -> None:
        other = _existing_link("leaf-1-Ethernet1__spine-2-Ethernet3", ["src", "elsewhere"])
        client = _client(existing_links=[other])
        src = _cabled_interface("src", "leaf-1", "Ethernet1")
        dst = _cabled_interface("dst", "spine-1", "Ethernet3")

        await connect_interface_maps(client, logging.getLogger(__name__), [(src, dst)])

        client.create.assert_awaited_once()
        other.save.assert_not_awaited()
