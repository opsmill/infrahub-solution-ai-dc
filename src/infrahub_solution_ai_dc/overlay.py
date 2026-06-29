from __future__ import annotations

from typing import TYPE_CHECKING, TypeVar

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

T = TypeVar("T")


def route_target(asn: int, vni: int) -> str:
    """Return the EVPN route-target string in the form "<asn>:<vni>"."""
    return f"{asn}:{vni}"


def resolve_segment_devices(rack_ids: Sequence[str], leafs_by_rack: Mapping[str, Sequence[T]]) -> list[T]:
    """Resolve the leaf devices that should carry a segment.

    `leafs_by_rack` maps a rack id to the leaf devices in that rack (the whole
    fabric's leafs, grouped by rack). When `rack_ids` is empty the segment is
    advertised on every leaf in the fabric (advertise-all default). Otherwise
    only the leafs of the listed racks carry it. Order is preserved and leafs
    are de-duplicated by identity (a rack id appearing twice is not doubled).
    """
    if rack_ids:
        candidates: list[T] = []
        for rack_id in rack_ids:
            candidates.extend(leafs_by_rack.get(rack_id, []))
    else:
        candidates = [leaf for leafs in leafs_by_rack.values() for leaf in leafs]

    seen: set[int] = set()
    resolved: list[T] = []
    for leaf in candidates:
        identity = id(leaf)
        if identity not in seen:
            seen.add(identity)
            resolved.append(leaf)

    return resolved
