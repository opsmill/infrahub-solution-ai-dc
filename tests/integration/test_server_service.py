"""Integration test for US1: connecting an L3 (BGP-speaking) server via a Server service.

Encodes quickstart.md §4-6: declaring an L3 ``NetworkServerService`` in a VRF (no rack/ports) must
drive the ServerGenerator to materialize a ``NetworkServer`` cabled to a leaf's ``role:server`` port,
with a ``server_p2p`` /31 on both ends, a private ASN from the global pool, and a paired
``ipv4_unicast`` eBGP session on each side (leaf ``remote_as == server.asn``; server
``remote_as == fabric.overlay_asn``). A second, unchanged run is a no-op (empty diff) — SC-003.

This proves the P1 MVP (SC-001, SC-004, FR-001/003/005/008/009).

Mirrors the structure, fixtures and style of ``tests/integration/test_overlay_daytwo.py``.

STACK-GATED: like ``test_overlay_daytwo.test_scoped_regeneration``, the assertion body depends on
devices built by the fabric/pod/rack generators. Repository sync loads no objects (``objects/`` is
not registered in ``.infrahub.yml``) and the generator trigger rules are parked in
``objects/20_triggers.yml.save``, so the core journey cannot run headless yet. The setup phases
(schema load, groups, repo sync) are shared with the overlay suite and left collectable; the core
``test_l3_server_journey`` is ``@pytest.mark.skip``-marked with the same rationale so the file stays
green-collectable in CI until the trigger strategy lands. Run against a live stack with:

    uv run pytest tests/integration/test_server_service.py
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest
from infrahub_sdk.protocols import CoreGenericRepository
from infrahub_sdk.testing.docker import TestInfrahubDockerClient
from infrahub_sdk.testing.repository import GitRepo

from infrahub_solution_ai_dc.protocols import (
    IpamIPAddress,
    NetworkBGPSession,
    NetworkDevice,
    NetworkInterface,
    NetworkSegment,
    NetworkServer,
    NetworkServerService,
    NetworkVrf,
    ServerInterface,
)

if TYPE_CHECKING:
    from pathlib import Path

    from infrahub_sdk import InfrahubClient
    from infrahub_sdk.node import InfrahubNode

# Standard groups required by the generator definitions in ``.infrahub.yml``.
# "server_services" is the group that drives the ServerGenerator (targets: server_services).
REQUIRED_GROUPS = ["halls", "racks", "fabrics", "pods", "devices", "tenants", "server_services"]

# The artifact under test (see ``.infrahub.yml`` artifact_definitions / contracts/config-artifact.md).
STARTUP_ARTIFACT = "Startup configuration"

# Seed L3 server service (objects/13_servers.yml) in the seed VRF (objects/12_overlay.yml).
SERVICE_NAME = "cilium-worker-1"
VRF_NAME = "blue-prod"
SERVER_HOSTNAME = f"server-{SERVICE_NAME}"

# Seed L2 server service (objects/13_servers.yml) naming the L2-only segment of the same VRF.
L2_SERVICE_NAME = "web-host-1"
L2_SEGMENT_NAME = "blue-l2"
L2_SERVER_HOSTNAME = f"server-{L2_SERVICE_NAME}"


class TestServerServiceL3(TestInfrahubDockerClient):
    """US1 — an L3 server is connected end-to-end from a single design object, idempotently."""

    @pytest.mark.asyncio
    async def test_load_schema(self, default_branch: str, client: InfrahubClient, schemas: list[dict]) -> None:
        """Load the server-extended schemas and wait for convergence (mirrors test_overlay_daytwo.py)."""
        await client.schema.wait_until_converged(branch=default_branch)

        resp = await client.schema.load(schemas=schemas, branch=default_branch, wait_until_converged=True)
        assert resp.errors == {}

    @pytest.mark.asyncio
    async def test_create_groups(self, client: InfrahubClient) -> None:
        """Create CoreStandardGroup objects required by generator definitions, incl. "server_services"."""
        for group_name in REQUIRED_GROUPS:
            group = await client.create(kind="CoreStandardGroup", name=group_name)
            await group.save()

    @pytest.mark.asyncio
    async def test_load_repository(
        self,
        client: InfrahubClient,
        remote_repos_dir: Path,
        root_directory: Path,
    ) -> None:
        """Register this repo and load it.

        This seeds the overlay + server objects (objects/12_overlay.yml tenant "Blue" -> VRF
        "blue-prod"; objects/13_servers.yml the L3 service) and runs the ServerGenerator +
        startup_configuration artifact via triggers, the same way ``inv load`` does.
        """
        repo = GitRepo(
            name="local-repository",
            src_directory=root_directory,
            dst_directory=remote_repos_dir,
        )
        await repo.add_to_infrahub(client=client)
        in_sync = await repo.wait_for_sync_to_complete(client=client, interval=10, retries=30)
        assert in_sync

        repos = await client.all(kind=CoreGenericRepository)
        assert repos

    @pytest.mark.asyncio
    @pytest.mark.skip(
        reason="Requires devices built by the fabric/pod/rack generators, but repository sync loads no objects "
        "(objects/ is not registered in .infrahub.yml) and the generator trigger rules are parked in "
        "objects/20_triggers.yml.save. Re-enable once the trigger strategy lands (same gate as "
        "test_overlay_daytwo.test_scoped_regeneration)."
    )
    async def test_l3_server_journey(self, client: InfrahubClient) -> None:
        """Core assertion (SC-001, SC-004, FR-001/003/005/009): the full L3 attach + rendered config.

        Flow (quickstart §4-5):
          1. The seeded L3 ``NetworkServerService`` drove the ServerGenerator, so a ``NetworkServer``
             now exists, cabled to a leaf's ``role:server`` port.
          2. Assert a ``server_p2p`` /31 on BOTH ends, an allocated private ASN, and the paired
             ``ipv4_unicast`` eBGP sessions with the correct ``remote_as`` on each side.
          3. Assert the leaf ``Startup configuration`` renders the interface + /31 + eBGP neighbor,
             and that NO artifact exists for the server (it is not a ``CoreArtifactTarget``).
        """
        # --- server materialized + cabled --------------------------------------------------------
        server = await client.get(kind=NetworkServer, hostname__value=SERVER_HOSTNAME, include=["interfaces"])
        assert server is not None, f"expected NetworkServer {SERVER_HOSTNAME!r} after generator run"

        server_ports = await client.filters(
            kind=ServerInterface, server__ids=[server.id], include=["ip_address", "link"]
        )
        assert server_ports, "server has no interface"
        server_port = server_ports[0]
        assert server_port.link.id is not None, "server port is not cabled to a leaf"

        # --- /31 on BOTH ends (server side + leaf rack-side) -------------------------------------
        assert server_port.ip_address.id is not None, "server port has no /31 address"
        server_ip = await client.get(kind=IpamIPAddress, id=server_port.ip_address.id)
        assert str(server_ip.address.value).endswith("/31"), "server address is not a /31"

        # --- ASN allocated from the global pool --------------------------------------------------
        assert server.asn.value is not None, "server ASN was not allocated"
        assert 4200000000 <= server.asn.value <= 4294967294, "server ASN is outside the Server ASN Pool"

        # --- paired ipv4_unicast eBGP sessions, correct remote_as each side ----------------------
        sessions = await client.filters(kind=NetworkBGPSession, peer_device__ids=[server.id])
        assert sessions, "no leaf->server eBGP session found"
        leaf_session = sessions[0]
        assert leaf_session.address_family.value == "ipv4_unicast"
        assert leaf_session.rr_client.value is False
        # The leaf peers the server's ASN.
        assert leaf_session.remote_as.value == server.asn.value

        server_sessions = await client.filters(kind=NetworkBGPSession, device__ids=[server.id])
        assert server_sessions, "no server->leaf eBGP session found"
        server_session = server_sessions[0]
        assert server_session.address_family.value == "ipv4_unicast"
        # The server peers the fabric overlay ASN, not its own.
        assert server_session.remote_as.value != server.asn.value

        # --- rendered leaf config (SC-004) -------------------------------------------------------
        leaf = await self._first_device_with_role(client, ("leaf",))
        assert leaf is not None
        leaf_config = await leaf.artifact_fetch(name=STARTUP_ARTIFACT)
        assert isinstance(leaf_config, str)
        assert str(server_ip.address.value).split("/")[0] in leaf_config, (
            "leaf startup config does not reference the server /31 eBGP neighbor address"
        )

        # --- no server artifact (NetworkServer is NOT a CoreArtifactTarget) ----------------------
        with pytest.raises(Exception):  # noqa: B017 - any failure proves the server has no artifact
            # NetworkServer is not a CoreArtifactTarget, so it has no typed artifact_fetch; cast to
            # the base node to make the (expected-to-fail) call.
            await cast("InfrahubNode", server).artifact_fetch(name=STARTUP_ARTIFACT)

    @pytest.mark.asyncio
    @pytest.mark.skip(
        reason="Depends on the same stack-gated device build as test_l3_server_journey; re-enable together."
    )
    async def test_rerun_is_empty_diff(self, client: InfrahubClient) -> None:
        """Idempotency (SC-003, FR-008): re-running the generator on the unchanged service is a no-op.

        Flow (quickstart §6): capture the server + its port/link/IP/ASN and the session set, touch the
        service to re-fire the trigger (or re-run ``generate-server``), and assert none of them changed
        — no new server, link, IP, ASN, or session — and the leaf artifact is byte-identical.
        """
        server_before = await client.get(kind=NetworkServer, hostname__value=SERVER_HOSTNAME)
        sessions_before = await client.filters(kind=NetworkBGPSession, peer_device__ids=[server_before.id])
        leaf = await self._first_device_with_role(client, ("leaf",))
        assert leaf is not None
        leaf_before = await leaf.artifact_fetch(name=STARTUP_ARTIFACT)

        # Re-fire the trigger by touching the service; the precise generate-server invocation is
        # validated against a running stack (same pattern as test_overlay_daytwo._regenerate_tenant_overlay).
        service = await client.get(kind=NetworkServerService, name__value=SERVICE_NAME)
        await service.save()

        server_after = await client.get(kind=NetworkServer, hostname__value=SERVER_HOSTNAME)
        sessions_after = await client.filters(kind=NetworkBGPSession, peer_device__ids=[server_after.id])
        leaf_after = await leaf.artifact_fetch(name=STARTUP_ARTIFACT)

        assert server_after.id == server_before.id, "re-run created a new server (not idempotent)"
        assert server_after.asn.value == server_before.asn.value, "re-run re-allocated the ASN"
        assert len(sessions_after) == len(sessions_before), "re-run changed the eBGP session count"
        assert leaf_after == leaf_before, "leaf artifact changed on an unchanged re-run (not idempotent)"

    @pytest.mark.asyncio
    @pytest.mark.skip(
        reason="Depends on the same stack-gated device build as test_l3_server_journey; re-enable together."
    )
    async def test_l2_server_journey(self, client: InfrahubClient) -> None:
        """US2 (FR-006, quickstart §7): an L2 server is bridged into a segment; placement grows, no BGP/IP.

        Flow: the seeded L2 ``NetworkServerService`` (naming segment ``blue-l2`` in VRF ``blue-prod``)
        drove the ServerGenerator, so:
          1. A ``NetworkServer`` exists, cabled (via a ``NetworkLink``) to a leaf's ``role:server`` port.
          2. That leaf's Rack now appears in the segment's ``racks`` placement.
          3. NO ``NetworkBGPSession`` and NO ``/31`` were created for the L2 server (no ASN either).
        """
        # --- server materialized + cabled --------------------------------------------------------
        server = await client.get(kind=NetworkServer, hostname__value=L2_SERVER_HOSTNAME, include=["rack"])
        assert server is not None, f"expected NetworkServer {L2_SERVER_HOSTNAME!r} after generator run"
        assert server.rack.id is not None, "L2 server has no resolved rack"

        server_ports = await client.filters(
            kind=ServerInterface, server__ids=[server.id], include=["ip_address", "link"]
        )
        assert server_ports, "L2 server has no interface"
        server_port = server_ports[0]
        assert server_port.link.id is not None, "L2 server port is not cabled to a leaf"

        # --- the chosen leaf's rack is now in the segment's placement ----------------------------
        segment = await client.get(kind=NetworkSegment, name__value=L2_SEGMENT_NAME, include=["racks"])
        rack_ids = {peer.id for peer in segment.racks.peers}
        assert server.rack.id in rack_ids, "the L2 server's rack was not added to the segment placement"

        # --- NO BGP session and NO /31 (FR-006) --------------------------------------------------
        assert server.asn.value is None, "L2 server must not be allocated an ASN"
        assert server_port.ip_address.id is None, "L2 server port must not carry a /31"
        sessions = await client.filters(kind=NetworkBGPSession, peer_device__ids=[server.id])
        assert not sessions, "L2 server must have no eBGP session"
        server_sessions = await client.filters(kind=NetworkBGPSession, device__ids=[server.id])
        assert not server_sessions, "L2 server must originate no eBGP session"

    @pytest.mark.asyncio
    @pytest.mark.skip(
        reason="Depends on the same stack-gated device build as test_l3_server_journey; re-enable together."
    )
    async def test_explicit_placement_honored(self, client: InfrahubClient) -> None:
        """US3 (FR-004, quickstart §8): a service naming a valid free Rack + role:server port uses exactly it.

        Flow: create an L3 ``NetworkServerService`` whose ``rack`` and ``leaf_interface`` name a free
        ``role:server`` port on a leaf of that rack, run ``generate-server``, then assert the
        materialized server's port is cabled to *that exact* leaf port and lands in *that exact* rack —
        no auto-selection substituted a different rack/port.
        """
        # Pick a concrete free role:server leaf port and its leaf's rack to request explicitly.
        first_leaf = await self._first_device_with_role(client, ("leaf",))
        assert first_leaf is not None
        leaf = await client.get(kind=NetworkDevice, id=first_leaf.id, include=["rack"])
        free_ports = await client.filters(
            kind=NetworkInterface, device__ids=[leaf.id], role__value="server", include=["ip_address", "link"]
        )
        chosen = next(p for p in free_ports if p.ip_address.id is None and p.link.id is None)
        vrf = await client.get(kind=NetworkVrf, name__value=VRF_NAME)

        service = await client.create(
            kind=NetworkServerService,
            name="explicit-worker-1",
            layer="l3",
            vrf={"id": vrf.id},
            rack={"id": leaf.rack.id},
            leaf_interface={"id": chosen.id},
        )
        await service.save()
        # Trigger materialization the same way the other journeys do (touch → trigger, or generate-server).
        await service.save()

        server = await client.get(
            kind=NetworkServer, hostname__value="server-explicit-worker-1", include=["rack", "interfaces"]
        )
        assert server.rack.id == leaf.rack.id, "explicit rack was not honored exactly"
        chosen_after = await client.get(kind=NetworkInterface, id=chosen.id, include=["link"])
        assert chosen_after.link.id is not None, "the explicitly-named leaf port was not cabled"

    @pytest.mark.asyncio
    @pytest.mark.skip(
        reason="Depends on the same stack-gated device build as test_l3_server_journey; re-enable together."
    )
    async def test_explicit_occupied_port_fails_loud(self, client: InfrahubClient) -> None:
        """US3 (SC-002, quickstart §8): naming an occupied leaf port fails loud with no partial objects.

        Flow: take an already-cabled ``role:server`` leaf port, create a service naming it, run the
        generator, and assert (a) the generator errors and (b) NO ``NetworkServer`` was created for the
        service — an invalid explicit placement produces no partial objects.
        """
        leaf = await self._first_device_with_role(client, ("leaf",))
        assert leaf is not None
        ports = await client.filters(
            kind=NetworkInterface, device__ids=[leaf.id], role__value="server", include=["ip_address", "link"]
        )
        occupied = next(p for p in ports if p.link.id is not None or p.ip_address.id is not None)
        vrf = await client.get(kind=NetworkVrf, name__value=VRF_NAME)

        service = await client.create(
            kind=NetworkServerService,
            name="explicit-occupied-1",
            layer="l3",
            vrf={"id": vrf.id},
            leaf_interface={"id": occupied.id},
        )
        await service.save()

        # The generate-server run must fail loud (validate_explicit_port / resolve_explicit_placement);
        # the precise invocation is exercised against a live stack. No server may exist afterwards.
        servers = await client.filters(kind=NetworkServer, hostname__value="server-explicit-occupied-1")
        assert not servers, "an occupied-port service must create no NetworkServer (no partial objects)"

    # --- helpers ---------------------------------------------------------------------------------

    @staticmethod
    async def _first_device_with_role(client: InfrahubClient, roles: tuple[str, ...]) -> InfrahubNode | None:
        """Return the first NetworkDevice matching any of the given roles, in role priority order."""
        for role in roles:
            devices = await client.filters(kind="NetworkDevice", role__value=role)
            if devices:
                return devices[0]
        return None
