from __future__ import annotations

from typing import TYPE_CHECKING, TypeVar

from .protocols import NetworkBGPSession

if TYPE_CHECKING:
    import logging
    from collections.abc import Mapping, Sequence

    from infrahub_sdk import InfrahubClient

    from .protocols import NetworkDevice

T = TypeVar("T")

# Clos tier ordering: a device reflects EVPN routes for the tiers below it (ADR-0005, formerly template-side).
TIER_RANK = {"super_spine": 2, "spine": 1, "leaf": 0}


def route_target(asn: int, vni: int) -> str:
    """Return the EVPN route-target string in the form "<asn>:<vni>"."""
    return f"{asn}:{vni}"


def rr_client(local_role: str, peer_role: str) -> bool:
    """Return True when the peer is an RR client of the local device (local tier outranks the peer's)."""
    return TIER_RANK.get(local_role, -1) > TIER_RANK.get(peer_role, -1)


async def upsert_evpn_session(
    client: InfrahubClient,
    logger: logging.Logger,
    device: NetworkDevice,
    peer: NetworkDevice,
    asn: int,
    *,
    peer_is_rr_client: bool,
) -> None:
    """Create or refresh the directional iBGP L2VPN-EVPN session from ``device`` toward ``peer``.

    Sessions are named "<device>__<peer>" (the upsert key), so re-running a generator refreshes the
    existing session instead of duplicating it.
    """
    session = await client.create(
        kind=NetworkBGPSession,
        name=f"{device.hostname.value}__{peer.hostname.value}",
        device={"id": device.id},
        peer_device={"id": peer.id},
        local_as=asn,
        remote_as=asn,
        address_family="l2vpn_evpn",
        rr_client=peer_is_rr_client,
    )
    await session.save(allow_upsert=True)
    logger.info(f"EVPN session {session.name.value} (rr_client={peer_is_rr_client})")


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
