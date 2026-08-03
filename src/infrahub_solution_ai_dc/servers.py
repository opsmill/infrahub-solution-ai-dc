"""Server-attachment helpers for the Server service (connect L2/L3 servers to leaves).

Two kinds of helper live here:

- **Pure functions** — :func:`select_least_utilized_rack` and :func:`select_free_server_port` —
  take plain node objects (no ``client``) so they are unit-testable with simple stubs, mirroring
  the pure helpers in :mod:`infrahub_solution_ai_dc.overlay`.
- **An SDK mutation** — :func:`upsert_ebgp_session` — creates the leaf<->server eBGP
  ``NetworkBGPSession`` and is modeled on :func:`infrahub_solution_ai_dc.overlay.upsert_evpn_session`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from netutils.interface import sort_interface_list

from .protocols import NetworkBGPSession

if TYPE_CHECKING:
    import logging
    from collections.abc import Iterable, Mapping, Sequence

    from infrahub_sdk import InfrahubClient

    from .protocols import LocationRack, NetworkBGPPeer, NetworkInterface


def require_allocated(value: int | None, pool_name: str) -> int:
    """Return ``value`` unchanged, or fail loud when a pool never allocated it (``vendors.py`` convention).

    Pure guard for the generator's pool-exhaustion paths (ASN / prefix pool): an allocation that
    silently yields ``None`` (an exhausted or misnamed pool) must fail loud rather than write a
    half-configured object. Raises ``ValueError`` naming ``pool_name`` when ``value is None``.
    """
    if value is None:
        msg = f"Pool {pool_name!r} did not allocate a value (pool exhausted or misnamed?)"
        raise ValueError(msg)
    return value


def _relationship_is_set(related: object) -> bool:
    """Return True when a to-one relationship points at a real node (a non-null ``id``)."""
    if related is None:
        return False
    return getattr(related, "id", None) is not None


def validate_service(
    layer: str,
    service_name: str,
    service_vrf_id: str,
    segment_id: str | None,
    segment_vrf_id: str | None,
) -> None:
    """Validate a ``NetworkServerService``'s L2/L3 intent, fail-loud (``vendors.py`` convention).

    Pure and synchronous so the fail-loud paths are directly unit-testable (unlike the async
    placement raises). The ``ServerGenerator`` calls this **before** creating any object, so an
    invalid request produces no partial objects. Rules (data-model.md):

    - ``layer == "l2"`` ⇒ a ``segment`` is **required** and ``segment.vrf`` must equal the service's
      ``vrf`` (an L2 host bridges into a segment of its own VRF).
    - ``layer == "l3"`` ⇒ a ``segment`` is **forbidden** — naming one is a contradictory request.

    ``segment_id``/``segment_vrf_id`` are the resolved segment's id and its VRF's id (both ``None``
    when the service names no segment). Raises ``ValueError`` naming the offending service.
    """
    if layer == "l2":
        if segment_id is None:
            msg = f"Server service {service_name!r} is L2 but names no segment; an L2 service requires a segment"
            raise ValueError(msg)
        if segment_vrf_id != service_vrf_id:
            msg = (
                f"Server service {service_name!r} names segment {segment_id!r} in VRF {segment_vrf_id!r}, "
                f"which is not the service's VRF {service_vrf_id!r}; an L2 segment must belong to the service's VRF"
            )
            raise ValueError(msg)
    elif segment_id is not None:
        msg = (
            f"Server service {service_name!r} is L3 but also names segment {segment_id!r}; "
            f"an L3 service must not name a segment (contradictory request)"
        )
        raise ValueError(msg)


def peer_endpoint_id(endpoint_ids: Iterable[str], own_endpoint_id: str) -> str | None:
    """Return the far end of a point-to-point link, or ``None`` when there is no single one.

    Used to recover a previous run's placement: a server's cabled port names a ``NetworkLink`` whose
    other endpoint *is* the leaf port that was chosen. Returns ``None`` for a half-built link (our own
    endpoint only) and for a link with several far ends — neither is a point-to-point server cable, and
    guessing would re-place a server that is already cabled.
    """
    others = [endpoint_id for endpoint_id in endpoint_ids if endpoint_id != own_endpoint_id]
    if len(others) != 1:
        return None
    return others[0]


def placement_matches_request(
    placed_rack_id: str,
    placed_port_id: str,
    requested_rack_id: str | None,
    requested_port_id: str | None,
) -> bool:
    """Return True when the service's ``rack``/``leaf_interface`` still describe the placement in the graph.

    ``rack`` and ``leaf_interface`` are round-trip fields: the operator may set them to request a
    placement, and the generator writes back whichever it resolved. So on a re-run they normally
    *equal* the materialized placement — that is the idempotent case this predicate detects, and the
    caller then reuses the placement untouched.

    An unset side matches anything: a service that requested nothing (or named only a rack) is placed
    automatically, and the run that placed it fills the remaining field in. A side that is set and
    *differs* means the operator re-pointed the service at a new rack or port, and the caller re-cables
    the server there rather than either ignoring the request or refusing it.
    """
    rack_matches = requested_rack_id is None or requested_rack_id == placed_rack_id
    port_matches = requested_port_id is None or requested_port_id == placed_port_id
    return rack_matches and port_matches


def select_least_utilized_rack(
    racks: Sequence[LocationRack],
    server_counts: Mapping[str, int],
) -> LocationRack | None:
    """Return the eligible rack hosting the fewest servers, deterministically.

    ``racks`` is the set of eligible racks; ``server_counts`` maps a rack ``id`` to the number of
    servers already attached to it (a rack absent from the mapping counts as zero). Ties are broken
    deterministically by the rack's ``index`` then its ``name`` so re-runs are stable. Returns
    ``None`` when ``racks`` is empty (the caller decides whether that is fail-loud).
    """
    if not racks:
        return None

    def sort_key(rack: LocationRack) -> tuple[int, int, str]:
        return (server_counts.get(rack.id, 0), rack.index.value, rack.name.value)

    return min(racks, key=sort_key)


def port_is_free(interface: NetworkInterface) -> bool:
    """Return True when a ``role: server`` interface is unused — no IP address and no cabled link.

    The "free" half of :func:`select_free_server_port`, factored out so every caller decides "in use"
    the same way: explicit-placement validation (:func:`validate_explicit_port`) rejects an occupied
    port on it, and the ``ServerGenerator`` uses it to notice that an honored explicit port needs
    releasing first.
    """
    return not _relationship_is_set(interface.ip_address) and not _relationship_is_set(interface.link)


def select_free_server_port(interfaces: Iterable[NetworkInterface]) -> NetworkInterface | None:
    """Return the lowest-numbered free ``role: server`` interface, or ``None`` if there is none.

    An interface is *free* when its ``role`` is ``"server"`` and it is unused — no IP address and no
    cabled link (both to-one relationships unset). "Lowest-numbered" is resolved with
    ``netutils.sort_interface_list`` over the candidate names, the same ordering the cabling helpers
    use.

    Candidates span *every* leaf of a rack, so the same port name legitimately occurs more than once
    (each leaf has an ``Ethernet1/1``). An exact-name tie therefore breaks on the owning device id,
    which keeps selection deterministic regardless of input order.
    """
    free = [interface for interface in interfaces if interface.role.value == "server" and port_is_free(interface)]
    if not free:
        return None

    lowest_name = sort_interface_list([interface.name.value for interface in free])[0]
    return min(
        (interface for interface in free if interface.name.value == lowest_name),
        key=lambda interface: getattr(interface.device, "id", "") or "",
    )


def validate_explicit_port(interface: NetworkInterface, rack_name: str, *, reclaimable: bool = False) -> None:
    """Fail-loud-validate an explicitly requested leaf port (US3/FR-004, ``vendors.py`` convention).

    Pure and synchronous so the honor-or-fail decision is directly unit-testable (unlike the async
    graph checks — rack∈fabric, port-on-a-leaf-of-the-rack, and who the port is cabled to — the
    ``ServerGenerator`` does around it). A valid explicit port must have ``role == "server"`` and be
    **unused** (the same "free" definition :func:`select_free_server_port` uses). Raises ``ValueError``
    naming the port and its rack on either violation; the generator calls this **before** any write, so
    a rejected explicit placement produces no partial objects. ``rack_name`` is only for the message.

    ``reclaimable`` waives the unused check for a port whose occupancy is *this service's own*
    leftovers — a cable to its own server, or a stale IP/half-link a deleted server left behind.
    ``ServerGenerator.port_is_reclaimable`` decides that (it needs the graph); the port is still
    required to be ``role: server``, and a port cabled to somebody else is never reclaimable.
    """
    port_name = interface.name.value
    role = interface.role.value
    if role != "server":
        msg = (
            f"Cannot honor explicit leaf_interface {port_name!r} on rack {rack_name!r}: "
            f"its role is {role!r}, not 'server'"
        )
        raise ValueError(msg)
    if not reclaimable and not port_is_free(interface):
        msg = (
            f"Cannot honor explicit leaf_interface {port_name!r} on rack {rack_name!r}: "
            f"the port is already in use (it has an IP address or a cabled link)"
        )
        raise ValueError(msg)


async def upsert_ebgp_session(
    client: InfrahubClient,
    logger: logging.Logger,
    device: NetworkBGPPeer,
    peer: NetworkBGPPeer,
    local_as: int,
    remote_as: int,
) -> None:
    """Create or refresh the directional eBGP ipv4-unicast session from ``device`` toward ``peer``.

    Sessions are named ``"<device>__<peer>"`` (the upsert key), so re-running a generator refreshes
    the existing session instead of duplicating it. Unlike the iBGP EVPN sessions, a server<->leaf
    eBGP session carries distinct ``local_as``/``remote_as`` and is never a route-reflector client.

    Saved with ``update_group_context=False``, like every other ``ServerGenerator`` write: the pair a
    move leaves behind is deleted explicitly (``ServerGenerator.delete_ebgp_pair``), so leaning on the
    generator group's cleanup to do it instead would only make the blast radius of that cleanup wider.
    """
    session = await client.create(
        kind=NetworkBGPSession,
        name=f"{device.hostname.value}__{peer.hostname.value}",
        device={"id": device.id},
        peer_device={"id": peer.id},
        local_as=local_as,
        remote_as=remote_as,
        address_family="ipv4_unicast",
        rr_client=False,
    )
    await session.save(allow_upsert=True, update_group_context=False)
    logger.info(f"eBGP session {session.name.value} (local_as={local_as}, remote_as={remote_as})")
