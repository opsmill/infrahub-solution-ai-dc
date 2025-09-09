from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import logging

    from infrahub_sdk import InfrahubClient

    from solution_ai_dc.protocols import NetworkInterface


def build_cabling_plan(
    logger: logging.Logger,  # noqa: ARG001
    pod_index: int,
    src_interface_map: dict[str, list[NetworkInterface]],
    dst_interface_map: dict[str, list[NetworkInterface]],
) -> list[tuple[NetworkInterface, NetworkInterface]]:
    """Builds a cabling plan between source and destination interfaces based in Indexes

    TODO Write unit test to validate that the algorithm works as expected
    """
    dst_device_names = list(dst_interface_map.keys())
    dst_device_count = len(dst_device_names)
    dst_interface_base_index = (pod_index - 2) * len(dst_interface_map)
    src_index = 0

    cabling_plan: list[tuple[NetworkInterface, NetworkInterface]] = []

    for src_interfaces in src_interface_map.values():
        dst_interface_index = dst_interface_base_index + src_index

        for dst_index, src_interface in enumerate(src_interfaces[:dst_device_count]):
            dst_interface = dst_interface_map[dst_device_names[dst_index]][dst_interface_index]

            cabling_plan.append((src_interface, dst_interface))

        src_index += 1  # noqa: SIM113 replace with enumerate
        dst_interface_index = dst_interface_base_index + src_index

    return cabling_plan


async def connect_interface_maps(
    client: InfrahubClient, logger: logging.Logger, cabling_plan: list[tuple[NetworkInterface, NetworkInterface]]
) -> None:
    for src_interface, dst_interface in cabling_plan:
        name = f"{src_interface.device.display_label}-{src_interface.name.value}__{dst_interface.device.display_label}-{dst_interface.name.value}"
        network_link = await client.create(
            kind="NetworkLink", name=name, medium="copper", endpoints=[src_interface, dst_interface]
        )
        await network_link.save(allow_upsert=True)
        logger.info(f"Connected {name}")
