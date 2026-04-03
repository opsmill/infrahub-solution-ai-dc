"""Tests for cabling plan algorithms."""

from typing import Any
from unittest.mock import MagicMock, PropertyMock

from infrahub_solution_ai_dc.cabling import (
    build_pod_cabling_plan,
    build_rack_cabling_plan,
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
