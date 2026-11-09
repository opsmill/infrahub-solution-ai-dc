"""Integration test for issue #120: re-cabling after a device rename keeps the existing link.

``connect_interface_maps`` names a ``NetworkLink`` after the display labels of its two devices. Before
the fix it upserted by that name, so after a rename the computed name no longer matched the existing
link and the upsert created a second link on an interface that already had one. Infrahub rejects that
with ``has 2 peers for networkendpoint__networklink, maximum of 1 allowed``.

The test calls ``connect_interface_maps`` directly rather than through the generator cascade: the
defect is in the helper, and a direct call needs only the schema, not the repository or the triggers.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import pytest
from infrahub_sdk.testing.docker import TestInfrahubDockerClient

from infrahub_solution_ai_dc.cabling import connect_interface_maps
from infrahub_solution_ai_dc.protocols import NetworkDevice, NetworkInterface, NetworkLink

if TYPE_CHECKING:
    from infrahub_sdk import InfrahubClient

LOGGER = logging.getLogger(__name__)


async def leaf_to_spine_plan(client: InfrahubClient) -> list[tuple[NetworkInterface, NetworkInterface]]:
    """The one-cable plan between ``Ethernet1`` on the leaf and ``Ethernet1`` on the spine."""
    leaf = await client.get(NetworkDevice, role__value="leaf")
    spine = await client.get(NetworkDevice, role__value="spine")
    leaf_port = await client.get(NetworkInterface, device__ids=[leaf.id], name__value="Ethernet1")
    spine_port = await client.get(NetworkInterface, device__ids=[spine.id], name__value="Ethernet1")
    return [(leaf_port, spine_port)]


class TestCablingAfterDeviceRename(TestInfrahubDockerClient):
    @pytest.mark.asyncio
    async def test_load_schema(self, default_branch: str, client: InfrahubClient, schemas: list[dict]) -> None:
        await client.schema.wait_until_converged(branch=default_branch)

        resp = await client.schema.load(schemas=schemas, branch=default_branch, wait_until_converged=True)
        assert resp.errors == {}

    @pytest.mark.asyncio
    async def test_cable_leaf_to_spine(self, client: InfrahubClient) -> None:
        for hostname, role in [("leaf-1", "leaf"), ("spine-1", "spine")]:
            device = await client.create(kind="NetworkDevice", hostname=hostname, role=role)
            await device.save()
            port = await client.create(kind="NetworkInterface", name="Ethernet1", device=device)
            await port.save()

        await connect_interface_maps(client, LOGGER, await leaf_to_spine_plan(client))

        links = await client.all(NetworkLink)
        assert [link.name.value for link in links] == ["leaf-1-Ethernet1__spine-1-Ethernet1"]

    @pytest.mark.asyncio
    async def test_recabling_after_a_rename_keeps_and_renames_the_link(self, client: InfrahubClient) -> None:
        (original,) = await client.all(NetworkLink)
        spine = await client.get(NetworkDevice, hostname__value="spine-1")
        spine.hostname.value = "spine-renamed"
        await spine.save()

        await connect_interface_maps(client, LOGGER, await leaf_to_spine_plan(client))

        links = await client.all(NetworkLink)
        assert [(link.id, link.name.value) for link in links] == [
            (original.id, "leaf-1-Ethernet1__spine-renamed-Ethernet1")
        ]

    @pytest.mark.asyncio
    async def test_recabling_without_changes_keeps_the_single_link(self, client: InfrahubClient) -> None:
        (original,) = await client.all(NetworkLink)

        await connect_interface_maps(client, LOGGER, await leaf_to_spine_plan(client))

        links = await client.all(NetworkLink)
        assert [link.id for link in links] == [original.id]
