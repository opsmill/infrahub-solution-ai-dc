from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING

from netutils.interface import sort_interface_list

if TYPE_CHECKING:
    from .protocols import NetworkDevice, NetworkInterface


def _group_by_device_in_name_order(
    interfaces: list[NetworkInterface],
    *,
    reverse: bool,
) -> dict[NetworkDevice, list[NetworkInterface]]:
    """Group interfaces by owning device, each device's list ordered by ``sort_interface_list``.

    The two orderings are exposed as separately named functions below because the schema's
    ``*_interface_sorting_method`` dropdown stores the function name as operator data
    (``schemas/logical_design.yml``), and the generators resolve it with ``getattr`` on this module.
    """
    by_device: dict[NetworkDevice, list[NetworkInterface]] = defaultdict(list)

    for interface in interfaces:
        by_device[interface.device.peer].append(interface)

    for device, device_interfaces in by_device.items():
        by_name = {interface.name.value: interface for interface in device_interfaces}
        ordered_names = sort_interface_list(list(by_name.keys()))
        if reverse:
            ordered_names.reverse()
        by_device[device] = [by_name[name] for name in ordered_names]

    return by_device


def create_sorted_device_interface_map(
    interfaces: list[NetworkInterface],
) -> dict[NetworkDevice, list[NetworkInterface]]:
    """Map each device to its own interfaces, in interface-name order."""
    return _group_by_device_in_name_order(interfaces, reverse=False)


def create_reverse_sorted_device_interface_map(
    interfaces: list[NetworkInterface],
) -> dict[NetworkDevice, list[NetworkInterface]]:
    """Map each device to its own interfaces, in reverse interface-name order."""
    return _group_by_device_in_name_order(interfaces, reverse=True)
