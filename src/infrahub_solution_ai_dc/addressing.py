from __future__ import annotations

from typing import TYPE_CHECKING

from .protocols import NetworkDevice, NetworkInterface

if TYPE_CHECKING:
    import logging
    from collections.abc import Generator
    from ipaddress import IPv4Address

    from infrahub_sdk import InfrahubClient
    from infrahub_sdk.protocols import CoreIPAddressPool, CoreIPPrefixPool


async def assign_ip_address_to_interface(
    client: InfrahubClient,
    interface: NetworkInterface,
    logger: logging.Logger,
    host_addresses: Generator[IPv4Address],
    prefix_len: int,
) -> None:
    ip_address = await client.create(kind="IpamIPAddress", address=str(next(host_addresses)) + f"/{prefix_len}")
    await ip_address.save(allow_upsert=True)
    interface = await client.get(NetworkInterface, id=interface.id, include=["link"])
    interface.ip_address = ip_address  # type: ignore[assignment]
    await interface.save(allow_upsert=True)
    logger.info(f"Assigned {ip_address.address.value} to {interface.display_label}")  # type: ignore[union-attr]


async def assign_ip_addresses_to_p2p_connections(
    client: InfrahubClient,
    logger: logging.Logger,
    connections: list[tuple[NetworkInterface, NetworkInterface]],
    prefix_len: int,
    prefix_role: str,
    pool: CoreIPPrefixPool,
) -> None:
    for src_interface, dst_interface in connections:
        # allocate a new prefix for the p2p connection
        prefix = await client.allocate_next_ip_prefix(
            resource_pool=pool,
            identifier=src_interface.id + dst_interface.id,
            member_type="address",
            prefix_length=prefix_len,
            data={"role": prefix_role},
        )

        logger.info(
            f"Allocated prefix {prefix.prefix.value} for connection between {src_interface.display_label}-{dst_interface.display_label}"  # type: ignore[union-attr]
        )

        host_addresses = prefix.prefix.value.hosts()  # type: ignore[union-attr]

        for interface in [src_interface, dst_interface]:
            await assign_ip_address_to_interface(client, interface, logger, host_addresses, prefix_len)


async def assign_vtep_loopback_to_device(
    client: InfrahubClient,
    logger: logging.Logger,
    device: NetworkDevice,
    vtep_pool: CoreIPAddressPool,
    interface_name: str = "Loopback1",
) -> None:
    """Allocate a VTEP loopback IP from the per-pod VTEP pool and bind it to a vtep-role loopback interface.

    The VTEP loopback (loopback1) is the NVE source on a leaf. It is distinct from loopback0 which stays the
    router-id / iBGP source. The same IpamIPAddress is referenced by ``NetworkDevice.vtep_ip`` and by the
    created interface, mirroring the loopback0 convention used for the underlay.
    """
    # Re-fetch the device fresh: the object the caller created still holds loopback_ip as the *pool* reference
    # (not the allocated address). A plain get resolves every relationship to its real peer, so setting vtep_ip
    # and saving neither sends an invalid reference nor clears loopback_ip (mirrors the ASN-stamping pattern).
    fresh = await client.get(kind=NetworkDevice, id=device.id)
    fresh.vtep_ip = vtep_pool  # type: ignore[assignment]  # pool object -> server-side from_pool allocation
    await fresh.save(allow_upsert=True)

    # FIX: the id of a related node assigned from a pool is not immediately accessible on the returned node
    fresh = await client.get(kind=NetworkDevice, id=device.id, include=["vtep_ip"])

    vtep_interface = await client.create(
        kind=NetworkInterface,
        name=interface_name,
        device=fresh,
        role="vtep",
        status="active",
        ip_address=fresh.vtep_ip.id,
    )
    await vtep_interface.save(allow_upsert=True)
    logger.info(f"Assigned VTEP loopback {fresh.vtep_ip.display_label} to {fresh.hostname.value}")
