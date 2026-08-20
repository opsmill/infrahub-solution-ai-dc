"""How a tier's interfaces are ordered before they are cabled to the tier above.

Which of the two orderings a fabric or pod uses is **operator data**: the
``*_interface_sorting_method`` dropdowns in ``schemas/logical_design.yml``, read by the pod and rack
generators. :data:`INTERFACE_ORDERINGS` is the registry those stored values resolve through, and
:func:`interface_ordering` is the only way to resolve one — a stored value that names nothing fails
loud, listing what it could have said (the ``vendors.py`` convention).

The registry keys are the **data contract**. They are what lives in ``objects/10_fabric.yml`` and in
every deployed database, so a key cannot be renamed without migrating that data — but the function a
key points at can be renamed freely, which is the whole reason the mapping is written out rather than
resolved by name off this module.
"""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING

from netutils.interface import sort_interface_list

if TYPE_CHECKING:
    from collections.abc import Callable

    from .protocols import NetworkDevice, NetworkInterface

    #: What every ordering in the registry is: a list of interfaces in, one list per device out.
    InterfaceOrdering = Callable[[list[NetworkInterface]], dict[NetworkDevice, list[NetworkInterface]]]


def _group_by_device_in_name_order(
    interfaces: list[NetworkInterface],
    *,
    reverse: bool,
) -> dict[NetworkDevice, list[NetworkInterface]]:
    """Group interfaces by owning device, each device's list ordered by ``sort_interface_list``."""
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


#: The orderings an operator can choose, keyed by the value stored in ``*_interface_sorting_method``.
#: ``tests/unit/test_sorting.py`` asserts these keys are exactly the schema's dropdown choices, so the
#: four copies of that list cannot drift away from what the code can actually resolve.
INTERFACE_ORDERINGS: dict[str, InterfaceOrdering] = {
    "create_sorted_device_interface_map": create_sorted_device_interface_map,
    "create_reverse_sorted_device_interface_map": create_reverse_sorted_device_interface_map,
}


def interface_ordering(method: str | None, *, design_object: str) -> InterfaceOrdering:
    """Resolve a stored ``*_interface_sorting_method`` to the ordering it names, or fail loud.

    Raises ``ValueError`` naming ``design_object`` and listing the supported values. Resolving through
    the registry rather than by attribute lookup on this module is what makes an unknown value say so:
    an attribute lookup would happily return any other name the module exports — ``sort_interface_list``
    or ``defaultdict`` — and fail much later, cabling the fabric wrongly or not at all.
    """
    if not method:
        msg = f"Cannot resolve an interface ordering for {design_object}: no sorting method set"
        raise ValueError(msg)

    ordering = INTERFACE_ORDERINGS.get(method)
    if ordering is None:
        msg = (
            f"Cannot resolve an interface ordering for {design_object}: {method!r} names no ordering "
            f"(supported: {', '.join(sorted(INTERFACE_ORDERINGS))})"
        )
        raise ValueError(msg)

    return ordering
