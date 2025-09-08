from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import logging
    from collections.abc import Generator
    from ipaddress import IPv4Address

    from infrahub_sdk import InfrahubClient
    from infrahub_sdk.node import InfrahubNode
    from infrahub_sdk.protocols import CoreIPPrefixPool

    from solution_ai_dc.protocols import NetworkInterface


async def assign_ip_address_to_interface(
    client: InfrahubClient,
    interface: NetworkInterface,
    logger: logging.Logger,
    host_addresses: Generator[IPv4Address],
    prefix_len: int,
) -> None:
    ip_address = await client.create(kind="IpamIPAddress", address=str(next(host_addresses)) + f"/{prefix_len}")
    await ip_address.save(allow_upsert=True)
    interface.ip_address = ip_address
    await interface.save(allow_upsert=True)
    logger.info(f"Assigned {ip_address.address.value} to {interface.display_label}")


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
            f"Allocated prefix {prefix.prefix.value} for connection between {src_interface.display_label}-{dst_interface.display_label}"
        )

        host_addresses = prefix.prefix.value.hosts()

        for interface in [src_interface, dst_interface]:
            await assign_ip_address_to_interface(client, interface, logger, host_addresses, prefix_len)
