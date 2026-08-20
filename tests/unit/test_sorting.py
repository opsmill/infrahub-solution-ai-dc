"""Tests for device interface sorting utilities and the ordering registry."""

from pathlib import Path
from unittest.mock import MagicMock, PropertyMock

import pytest
import yaml

from infrahub_solution_ai_dc.sorting import (
    INTERFACE_ORDERINGS,
    create_reverse_sorted_device_interface_map,
    create_sorted_device_interface_map,
    interface_ordering,
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


class TestInterfaceOrderingRegistry:
    """The registry is the data contract for ``*_interface_sorting_method``."""

    def test_each_key_resolves_to_its_ordering(self) -> None:
        assert interface_ordering("create_sorted_device_interface_map", design_object="fabric x") is (
            create_sorted_device_interface_map
        )
        assert interface_ordering("create_reverse_sorted_device_interface_map", design_object="fabric x") is (
            create_reverse_sorted_device_interface_map
        )

    def test_an_unknown_method_fails_loud_and_lists_what_is_supported(self) -> None:
        """An attribute lookup would have returned some unrelated module member and failed far later."""
        with pytest.raises(ValueError, match="names no ordering") as raised:
            interface_ordering("sort_interface_list", design_object="pod pod-a1")

        assert "pod pod-a1" in str(raised.value)
        assert "create_sorted_device_interface_map" in str(raised.value)

    @pytest.mark.parametrize("method", [None, ""])
    def test_an_unset_method_fails_loud(self, method: str | None) -> None:
        """A design object that never had one is a data gap, not a reason to guess a default."""
        with pytest.raises(ValueError, match="no sorting method set"):
            interface_ordering(method, design_object="fabric fabric-1")

    def test_the_registry_matches_every_schema_dropdown(self) -> None:
        """The four dropdowns and the registry name the same set, or an operator can store a value
        the generators cannot resolve.

        ``schemas/logical_design.yml`` repeats the choice list once per attribute
        (``fabric_``/``spine_`` on the fabric, ``leaf_``/``spine_`` on the pod). Asserting each list
        separately is what keeps one of the four from drifting unnoticed.
        """
        schema = yaml.safe_load(Path("schemas/logical_design.yml").read_text(encoding="utf-8"))

        dropdowns = [
            (node["name"], attribute["name"], [choice["name"] for choice in attribute["choices"]])
            for node in schema["nodes"]
            for attribute in node.get("attributes", [])
            if attribute["name"].endswith("_interface_sorting_method")
        ]

        assert len(dropdowns) == 4, f"expected four sorting dropdowns, found {[d[:2] for d in dropdowns]}"
        for node_name, attribute_name, choices in dropdowns:
            assert sorted(choices) == sorted(INTERFACE_ORDERINGS), f"{node_name}.{attribute_name}"

    def test_every_schema_default_is_a_registry_key(self) -> None:
        """A default that resolves to nothing would break every fabric that never set the field."""
        schema = yaml.safe_load(Path("schemas/logical_design.yml").read_text(encoding="utf-8"))

        defaults = [
            attribute["default_value"]
            for node in schema["nodes"]
            for attribute in node.get("attributes", [])
            if attribute["name"].endswith("_interface_sorting_method")
        ]

        assert defaults
        for default in defaults:
            assert default in INTERFACE_ORDERINGS
