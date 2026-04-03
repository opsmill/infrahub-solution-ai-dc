"""Tests for device interface sorting utilities."""

from unittest.mock import MagicMock, PropertyMock

from infrahub_solution_ai_dc.sorting import (
    create_reverse_sorted_device_interface_map,
    create_sorted_device_interface_map,
)


def _make_interface(device_peer: object, name: str) -> MagicMock:
    """Create a mock NetworkInterface with the given device peer and name."""
    intf = MagicMock()
    intf.device.peer = device_peer
    type(intf.name).value = PropertyMock(return_value=name)
    return intf


class TestCreateSortedDeviceInterfaceMap:
    def test_single_device_sorted(self) -> None:
        device = MagicMock()
        intf3 = _make_interface(device, "Ethernet3")
        intf1 = _make_interface(device, "Ethernet1")
        intf2 = _make_interface(device, "Ethernet2")

        result = create_sorted_device_interface_map([intf3, intf1, intf2])

        assert list(result.keys()) == [device]
        names = [i.name.value for i in result[device]]
        assert names == ["Ethernet1", "Ethernet2", "Ethernet3"]

    def test_multiple_devices(self) -> None:
        dev_a = MagicMock()
        dev_b = MagicMock()
        intf_a1 = _make_interface(dev_a, "Ethernet2")
        intf_a2 = _make_interface(dev_a, "Ethernet1")
        intf_b1 = _make_interface(dev_b, "Ethernet1")

        result = create_sorted_device_interface_map([intf_a1, intf_a2, intf_b1])

        assert len(result) == 2
        assert [i.name.value for i in result[dev_a]] == ["Ethernet1", "Ethernet2"]
        assert [i.name.value for i in result[dev_b]] == ["Ethernet1"]

    def test_empty_input(self) -> None:
        result = create_sorted_device_interface_map([])
        assert dict(result) == {}


class TestCreateReverseSortedDeviceInterfaceMap:
    def test_reverse_order(self) -> None:
        device = MagicMock()
        intf1 = _make_interface(device, "Ethernet1")
        intf2 = _make_interface(device, "Ethernet2")
        intf3 = _make_interface(device, "Ethernet3")

        result = create_reverse_sorted_device_interface_map([intf1, intf2, intf3])

        names = [i.name.value for i in result[device]]
        assert names == ["Ethernet3", "Ethernet2", "Ethernet1"]

    def test_empty_input(self) -> None:
        result = create_reverse_sorted_device_interface_map([])
        assert dict(result) == {}
