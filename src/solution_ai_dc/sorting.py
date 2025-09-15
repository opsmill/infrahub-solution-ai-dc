from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING

from netutils.interface import sort_interface_list

if TYPE_CHECKING:
    from solution_ai_dc.protocols import NetworkDevice, NetworkInterface


def create_sorted_device_interface_map(interfaces: list[NetworkInterface]) -> dict[NetworkDevice, list[NetworkInterface]]:
    """
    Creates a dictionary that maps a device hostname to a sorted list of interfaces from a list of interfaces
    """

    device_interface_map = defaultdict(list)

    for interface in interfaces:
        device_interface_map[interface.device.peer].append(interface)

    for device, intfs in device_interface_map.items():
        interface_map = {interface.name.value: interface for interface in intfs}
        sorted_interface_names = sort_interface_list(list(interface_map.keys()))
        device_interface_map[device] = [interface_map[interface] for interface in sorted_interface_names]

    return device_interface_map
