"""Integration tests for the Server service: connecting L3 (BGP-speaking) and L2 servers.

Encodes quickstart.md §4-8. Declaring a ``NetworkServerService`` must drive the ServerGenerator to
materialize a ``NetworkServer`` cabled to a leaf's ``role:server`` port; for L3 that means a
``server_p2p`` /31 on both ends, a private ASN from the global pool, and a paired ``ipv4_unicast``
eBGP session on each side (leaf ``remote_as == server.asn``; server ``remote_as ==
fabric.overlay_asn``). An unchanged re-run is a no-op (SC-003). Proves SC-001/002 and
FR-001/003/004/005/006/008/009. SC-004 (the rendered leaf config) is not asserted -- see
``test_l3_server_journey`` for why no startup-config artifact exists to assert on.

These tests were skipped from the day they were written, because their assertions need leaf devices
and the suite had no way to build them. They now drive the real cascade via
``tests/integration/cascade.py`` (see ``test_provision_cascade``), which is why the two things that
kept the cascade from firing are handled explicitly here:

* ``triggers.yml`` is loaded by neither ``inv load`` nor repository sync, so it is loaded directly.
* Every rule is ``branch_scope: other_branches``, so nothing can cascade on ``main``. Every assertion
  below runs on ``SERVER_BRANCH``.

The generator is also invoked explicitly rather than by touching an object and hoping a trigger
fires: a ``save()`` that changes no field writes nothing, emits no NodeUpdatedEvent, and therefore
dispatches nothing -- which is exactly why the earlier drafts of these tests could not have passed.

Scope note: only the Fabric-A seed services are exercised. ``objects/13_servers.yml`` also seeds two
Green services on Fabric-D, and this suite cascades Fabric-A only, so generating those would fail for
want of leaves.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from infrahub_sdk.protocols import CoreGenericRepository
from infrahub_sdk.schema import NodeSchemaAPI
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
from tests.integration.cascade import (
    GENERATOR_TIMEOUT,
    NO_CASCADE_WINDOW,
    load_trigger_rules,
    provision_fabric_cascade,
    run_generator,
    stays_false,
    wait_until,
)

if TYPE_CHECKING:
    from pathlib import Path

    from infrahub_sdk import InfrahubClient

# Standard groups the generator definitions target. The per-vendor device groups, server_services and
# kubernetes_clusters arrive with objects/01_groups.yml during repository sync.
REQUIRED_GROUPS = ["halls", "racks", "fabrics", "pods", "devices", "tenants", "server_services"]

# Every rule in triggers.yml is branch_scope: other_branches, so the cascade cannot run on main.
SERVER_BRANCH = "server-service-test"

# The artifact under test. All four per-vendor artifact_definitions publish under this one
# ``artifact_name`` (.infrahub.yml); the per-vendor ``name`` above it is internal.
STARTUP_ARTIFACT = "Startup configuration"

# Seed L3 service (objects/13_servers.yml) in the seed VRF (objects/12_overlay.yml). It names
# Rack-A2-2 explicitly, so placement is deterministic rather than least-utilized.
SERVICE_NAME = "cilium-worker-1"
VRF_NAME = "blue-prod"
SERVER_HOSTNAME = f"server-{SERVICE_NAME}"

# Seed L2 service naming the L2-only segment of the same VRF, on Rack-A3-2.
L2_SERVICE_NAME = "web-host-1"
L2_SEGMENT_NAME = "blue-l2"
L2_SERVER_HOSTNAME = f"server-{L2_SERVICE_NAME}"

# The two Fabric-A services this suite materializes. Kept explicit rather than "every service in the
# group" precisely to exclude the Fabric-D ones.
SEED_SERVICES = (SERVICE_NAME, L2_SERVICE_NAME)

# Private-use ASN range the Server ASN Pool allocates from (schemas/routing.yml).
ASN_POOL_MIN = 4200000000
ASN_POOL_MAX = 4294967294


async def generate_services(client: InfrahubClient, *, service_names: tuple[str, ...] | list[str]) -> None:
    """Run ``generate-server`` for named services and wait until each one is *completely* materialized.

    Waits on the resulting data rather than on the task, because ``run_generator`` submits with
    ``wait_until_completion: false`` to keep a long generator run from tripping the client HTTP timeout.

    The gate deliberately checks the *last* thing the generator does, not the first. ``NetworkServer``
    is created early, then cabled, and only then does ``configure_l3`` allocate the ASN and the /31 and
    upsert the eBGP pair (generate_server.py). Gating on "a server exists" therefore returns while
    addressing is still in flight -- which made ``test_l3_server_journey`` fail on a null ip_address and
    made ``test_rerun_is_empty_diff`` see the *first* run's sessions still appearing and report the
    re-run as non-idempotent. Same trap the generator-chain suite documents: "the tier ran" and "the
    tier finished its work" are different claims, and only the second is safe to assert against.

    ``pending`` names what each server is still missing, so a timeout says "no /31" rather than just
    "not ready".
    """
    services = [
        await client.get(kind=NetworkServerService, branch=SERVER_BRANCH, name__value=name) for name in service_names
    ]
    expected_layers = {f"server-{service.name.value}": str(service.layer.value) for service in services}

    await run_generator(
        client,
        definition_name="generate-server",
        branch=SERVER_BRANCH,
        node_ids=[service.id for service in services],
    )

    pending: dict[str, str] = {}

    async def all_servers_converged() -> bool:
        pending.clear()
        servers = {
            str(server.hostname.value): server for server in await client.filters(kind=NetworkServer, branch=SERVER_BRANCH)
        }

        for hostname, layer in expected_layers.items():
            server = servers.get(hostname)
            if server is None:
                pending[hostname] = "no NetworkServer"
                continue

            ports = await client.filters(
                kind=ServerInterface,
                branch=SERVER_BRANCH,
                server__ids=[server.id],
                include=["ip_address", "link"],
            )
            if not ports:
                pending[hostname] = "no ServerInterface"
                continue
            if ports[0].link.id is None:
                pending[hostname] = "not cabled to a leaf"
                continue

            # L2 stops here by design: no ASN, no /31, no session (FR-006).
            if layer != "l3":
                continue

            if ports[0].ip_address.id is None:
                pending[hostname] = "no /31 on the server port"
            elif server.asn.value is None:
                pending[hostname] = "no ASN allocated"
            elif not await client.count(kind=NetworkBGPSession, branch=SERVER_BRANCH, device__ids=[server.id]):
                pending[hostname] = "no server-side eBGP session"
            elif not await client.count(kind=NetworkBGPSession, branch=SERVER_BRANCH, peer_device__ids=[server.id]):
                pending[hostname] = "no leaf-side eBGP session"

        return not pending

    await wait_until(
        all_servers_converged,
        what=lambda: "generate-server to finish: "
        + ", ".join(f"{host} ({reason})" for host, reason in sorted(pending.items())),
        timeout_seconds=GENERATOR_TIMEOUT,
    )


class TestServerServiceL3(TestInfrahubDockerClient):
    """An L3 and an L2 server are connected end-to-end from a single design object, idempotently."""

    # --- setup -----------------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_load_schema(self, default_branch: str, client: InfrahubClient, schemas: list[dict]) -> None:
        """Load the server-extended schemas and wait for convergence."""
        await client.schema.wait_until_converged(branch=default_branch)

        resp = await client.schema.load(schemas=schemas, branch=default_branch, wait_until_converged=True)
        assert resp.errors == {}

    @pytest.mark.asyncio
    async def test_create_groups(self, client: InfrahubClient) -> None:
        """Create the CoreStandardGroup objects the generator definitions target."""
        for group_name in REQUIRED_GROUPS:
            group = await client.create(kind="CoreStandardGroup", name=group_name)
            await group.save()

    @pytest.mark.asyncio
    async def test_load_repository(
        self,
        client: InfrahubClient,
        remote_repos_dir: Path,
        repo_source_directory: Path,
    ) -> None:
        """Register and sync this repo: generator definitions, queries and the objects/ seed.

        This seeds the overlay + server objects (objects/12_overlay.yml tenant "Blue" -> VRF
        "blue-prod"; objects/13_servers.yml the services), the same way ``inv load`` does.
        """
        repo = GitRepo(
            name="local-repository",
            src_directory=repo_source_directory,
            dst_directory=remote_repos_dir,
        )
        await repo.add_to_infrahub(client=client)
        in_sync = await repo.wait_for_sync_to_complete(client=client, interval=10, retries=30)
        assert in_sync

        repos = await client.all(kind=CoreGenericRepository)
        assert repos

    @pytest.mark.asyncio
    async def test_load_trigger_rules(self, client: InfrahubClient, root_directory: Path) -> None:
        """Load triggers.yml -- the step neither ``inv load`` nor repository sync performs."""
        await load_trigger_rules(client, root_directory)

    @pytest.mark.asyncio
    async def test_provision_cascade(self, client: InfrahubClient) -> None:
        """Build the fabric the servers attach to: fabric -> pod -> rack, on a non-default branch.

        This is the setup whose absence kept every assertion below skipped. It is asserted as its own
        phase so a cascade failure is reported as such, instead of surfacing later as a puzzling
        "expected NetworkServer ... after generator run".
        """
        await client.branch.create(branch_name=SERVER_BRANCH, sync_with_git=False)
        await provision_fabric_cascade(client, branch=SERVER_BRANCH)

        leaves = await client.count(kind=NetworkDevice, branch=SERVER_BRANCH, role__value="leaf")
        assert leaves, "the cascade produced no leaf devices; the server tests cannot place anything"

    @pytest.mark.asyncio
    async def test_generate_seed_servers(self, client: InfrahubClient) -> None:
        """Materialize the seed L3 and L2 services, so the journeys below only have to assert."""
        await generate_services(client, service_names=SEED_SERVICES)

    # --- L3 journey ------------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_l3_server_journey(self, client: InfrahubClient) -> None:
        """Core assertion (SC-001, FR-001/003/005/009): the full L3 attach.

        The seeded L3 ``NetworkServerService`` drove the ServerGenerator, so a ``NetworkServer`` now
        exists cabled to a leaf's ``role:server`` port. Asserts a ``server_p2p`` /31 on the server
        end, an allocated private ASN, and the paired ``ipv4_unicast`` eBGP sessions with the correct
        ``remote_as`` on each side.

        SC-004 (the leaf's rendered config referencing the /31 neighbor) is deliberately NOT asserted
        here. Measured against a live 1.11.0b1 stack, no ``Startup configuration`` artifact exists for
        any device -- the per-vendor artifact_definitions are imported and the devices do join their
        ``{vendor}_devices`` group, but nothing generates those artifacts on group membership, and
        ``artifact_generate`` only regenerates one that already exists. Both it and ``artifact_fetch``
        raise ``NodeNotFoundError``. Asserting on the render would test artifact scheduling rather than
        the attach; the BGP session state asserted below is what the template reads anyway.
        """
        server = await client.get(
            kind=NetworkServer, branch=SERVER_BRANCH, hostname__value=SERVER_HOSTNAME, include=["interfaces"]
        )
        assert server is not None, f"expected NetworkServer {SERVER_HOSTNAME!r} after generator run"

        server_ports = await client.filters(
            kind=ServerInterface, branch=SERVER_BRANCH, server__ids=[server.id], include=["ip_address", "link"]
        )
        assert server_ports, "server has no interface"
        server_port = server_ports[0]
        assert server_port.link.id is not None, "server port is not cabled to a leaf"

        # --- /31 on the server end ---------------------------------------------------------------
        assert server_port.ip_address.id is not None, "server port has no /31 address"
        server_ip = await client.get(kind=IpamIPAddress, branch=SERVER_BRANCH, id=server_port.ip_address.id)
        assert str(server_ip.address.value).endswith("/31"), "server address is not a /31"

        # --- ASN allocated from the global pool --------------------------------------------------
        assert server.asn.value is not None, "server ASN was not allocated"
        assert ASN_POOL_MIN <= server.asn.value <= ASN_POOL_MAX, "server ASN is outside the Server ASN Pool"

        # --- paired ipv4_unicast eBGP sessions, correct remote_as each side ----------------------
        sessions = await client.filters(kind=NetworkBGPSession, branch=SERVER_BRANCH, peer_device__ids=[server.id])
        assert sessions, "no leaf->server eBGP session found"
        leaf_session = sessions[0]
        assert leaf_session.address_family.value == "ipv4_unicast"
        assert leaf_session.rr_client.value is False
        # The leaf peers the server's ASN.
        assert leaf_session.remote_as.value == server.asn.value

        server_sessions = await client.filters(kind=NetworkBGPSession, branch=SERVER_BRANCH, device__ids=[server.id])
        assert server_sessions, "no server->leaf eBGP session found"
        server_session = server_sessions[0]
        assert server_session.address_family.value == "ipv4_unicast"
        # The server peers the fabric overlay ASN, not its own.
        assert server_session.remote_as.value != server.asn.value

    @pytest.mark.asyncio
    async def test_server_is_not_an_artifact_target(self, client: InfrahubClient) -> None:
        """``NetworkServer`` renders no config of its own -- only the leaf side is materialized.

        Asserted against the schema, not by expecting ``artifact_fetch`` to raise. Measured against a
        live 1.11.0b1 stack, no ``Startup configuration`` artifact exists for *any* device: the
        per-vendor artifact_definitions are imported and devices do join their ``{vendor}_devices``
        group, but nothing generates those artifacts on group membership, so ``artifact_fetch`` raises
        ``NodeNotFoundError`` for a leaf exactly as it does for a server. An "it raises" test would
        therefore pass whatever the schema said -- it would prove nothing at all.

        ``inherit_from`` is the real contract: it is what makes the platform treat a kind as an
        artifact target, and it cannot pass vacuously.
        """
        server_schema = await client.schema.get(kind="NetworkServer", branch=SERVER_BRANCH)
        # ``schema.get`` returns a union (node/generic/profile/template); only a node schema carries
        # ``inherit_from``, and NetworkServer being anything else would itself be the bug.
        assert isinstance(server_schema, NodeSchemaAPI)
        assert "CoreArtifactTarget" not in server_schema.inherit_from, (
            "NetworkServer inherits CoreArtifactTarget; it would be swept into the startup-config "
            "artifacts, which must only ever render the leaf side"
        )

        # Control: a kind that *is* an artifact target, so a schema-shape change that broke the
        # attribute (renamed, always empty) fails here instead of silently passing above.
        device_schema = await client.schema.get(kind="NetworkDevice", branch=SERVER_BRANCH)
        assert isinstance(device_schema, NodeSchemaAPI)
        assert "CoreArtifactTarget" in device_schema.inherit_from, (
            "NetworkDevice no longer inherits CoreArtifactTarget; the assertion above is now vacuous"
        )

    @pytest.mark.asyncio
    async def test_rerun_is_empty_diff(self, client: InfrahubClient) -> None:
        """Idempotency (SC-003, FR-008): re-running the generator on an unchanged service is a no-op.

        Re-runs ``generate-server`` explicitly and then holds for a window, rather than touching the
        service and asserting immediately: the run is submitted asynchronously, so an immediate
        re-read would pass even if the re-run were about to duplicate everything.
        """
        server_before = await client.get(kind=NetworkServer, branch=SERVER_BRANCH, hostname__value=SERVER_HOSTNAME)
        sessions_before = await client.count(
            kind=NetworkBGPSession, branch=SERVER_BRANCH, peer_device__ids=[server_before.id]
        )
        servers_before = await client.count(kind=NetworkServer, branch=SERVER_BRANCH)

        await generate_services(client, service_names=(SERVICE_NAME,))

        async def anything_changed() -> bool:
            servers = await client.filters(kind=NetworkServer, branch=SERVER_BRANCH)
            if len(servers) != servers_before:
                return True
            current = next((item for item in servers if item.hostname.value == SERVER_HOSTNAME), None)
            if current is None or current.id != server_before.id:
                return True
            if current.asn.value != server_before.asn.value:
                return True
            sessions = await client.count(
                kind=NetworkBGPSession, branch=SERVER_BRANCH, peer_device__ids=[server_before.id]
            )
            return sessions != sessions_before

        assert await stays_false(anything_changed, window=NO_CASCADE_WINDOW), (
            "an unchanged re-run altered the server, its ASN, or its session count; generate-server is not idempotent"
        )

    # --- L2 journey ------------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_l2_server_journey(self, client: InfrahubClient) -> None:
        """FR-006 (quickstart §7): an L2 server is bridged into a segment; no BGP, no IP, no ASN.

        The seeded L2 service names segment ``blue-l2`` in VRF ``blue-prod``, so the generator must
        cable a server, add its rack to that segment's placement, and allocate nothing else.
        """
        server = await client.get(
            kind=NetworkServer, branch=SERVER_BRANCH, hostname__value=L2_SERVER_HOSTNAME, include=["rack"]
        )
        assert server is not None, f"expected NetworkServer {L2_SERVER_HOSTNAME!r} after generator run"
        assert server.rack.id is not None, "L2 server has no resolved rack"

        server_ports = await client.filters(
            kind=ServerInterface, branch=SERVER_BRANCH, server__ids=[server.id], include=["ip_address", "link"]
        )
        assert server_ports, "L2 server has no interface"
        server_port = server_ports[0]
        assert server_port.link.id is not None, "L2 server port is not cabled to a leaf"

        # --- the chosen leaf's rack is now in the segment's placement ----------------------------
        segment = await client.get(
            kind=NetworkSegment, branch=SERVER_BRANCH, name__value=L2_SEGMENT_NAME, include=["racks"]
        )
        rack_ids = {peer.id for peer in segment.racks.peers}
        assert server.rack.id in rack_ids, "the L2 server's rack was not added to the segment placement"

        # --- NO BGP session, NO /31, NO ASN (FR-006) ---------------------------------------------
        assert server.asn.value is None, "L2 server must not be allocated an ASN"
        assert server_port.ip_address.id is None, "L2 server port must not carry a /31"
        assert not await client.count(kind=NetworkBGPSession, branch=SERVER_BRANCH, peer_device__ids=[server.id]), (
            "L2 server must have no eBGP session"
        )
        assert not await client.count(kind=NetworkBGPSession, branch=SERVER_BRANCH, device__ids=[server.id]), (
            "L2 server must originate no eBGP session"
        )

    # --- explicit placement ----------------------------------------------------------------------
    #
    # These two run last: both consume free role:server ports, and the occupied-port test needs a
    # port that an earlier journey already cabled.

    @pytest.mark.asyncio
    async def test_explicit_placement_honored(self, client: InfrahubClient) -> None:
        """FR-004 (quickstart §8): a service naming a free ``role:server`` port uses exactly it.

        Asserts the exact port, not merely "a port was cabled": the whole point of explicit placement
        is that auto-selection did not substitute a different rack or port.
        """
        leaf, chosen = await self._leaf_with_free_server_port(client)
        vrf = await client.get(kind=NetworkVrf, branch=SERVER_BRANCH, name__value=VRF_NAME)

        service = await client.create(
            kind=NetworkServerService,
            branch=SERVER_BRANCH,
            name="explicit-worker-1",
            layer="l3",
            vrf=vrf.id,
            rack=leaf.rack.id,
            leaf_interface=chosen.id,
            # Without this the service is not in the group the generator definition targets.
            member_of_groups=["server_services"],
        )
        await service.save()

        await generate_services(client, service_names=("explicit-worker-1",))

        server = await client.get(
            kind=NetworkServer,
            branch=SERVER_BRANCH,
            hostname__value="server-explicit-worker-1",
            include=["rack", "interfaces"],
        )
        assert server.rack.id == leaf.rack.id, "explicit rack was not honored exactly"

        chosen_after = await client.get(kind=NetworkInterface, branch=SERVER_BRANCH, id=chosen.id, include=["link"])
        assert chosen_after.link.id is not None, "the explicitly-named leaf port was not cabled"

        # The cable must join the *requested* port to this server, not merely exist.
        server_ports = await client.filters(
            kind=ServerInterface, branch=SERVER_BRANCH, server__ids=[server.id], include=["link"]
        )
        assert server_ports, "explicitly-placed server has no interface"
        assert any(port.link.id == chosen_after.link.id for port in server_ports), (
            "the server is cabled to a different port than the one explicitly requested"
        )

    @pytest.mark.asyncio
    async def test_explicit_occupied_port_fails_loud(self, client: InfrahubClient) -> None:
        """SC-002 (quickstart §8): naming an occupied leaf port produces no partial objects.

        The generator is actually run here, and the absence of a server is then held over a window.
        A bare "no server exists" assertion would pass even if the generator had never been
        dispatched, which is what the earlier draft of this test did.
        """
        occupied = await self._occupied_server_port(client)
        vrf = await client.get(kind=NetworkVrf, branch=SERVER_BRANCH, name__value=VRF_NAME)

        service = await client.create(
            kind=NetworkServerService,
            branch=SERVER_BRANCH,
            name="explicit-occupied-1",
            layer="l3",
            vrf=vrf.id,
            leaf_interface=occupied.id,
            member_of_groups=["server_services"],
        )
        await service.save()

        # Submitted directly rather than through ``generate_services``: that helper waits for the
        # server to appear, and here the whole point is that it never does.
        await run_generator(
            client, definition_name="generate-server", branch=SERVER_BRANCH, node_ids=[service.id]
        )

        async def server_materialized() -> bool:
            return bool(
                await client.count(
                    kind=NetworkServer, branch=SERVER_BRANCH, hostname__value="server-explicit-occupied-1"
                )
            )

        assert await stays_false(server_materialized, window=NO_CASCADE_WINDOW), (
            "an occupied-port service created a NetworkServer; explicit placement must fail loud with "
            "no partial objects (validate_explicit_port / resolve_explicit_placement)"
        )

    # --- helpers ---------------------------------------------------------------------------------

    @staticmethod
    async def _leaf_with_free_server_port(client: InfrahubClient) -> tuple[NetworkDevice, NetworkInterface]:
        """Return a leaf and one of its free ``role:server`` ports.

        Scans every leaf rather than trusting the first: the seed journeys above have already consumed
        ports, and a leaf whose server ports are all taken would otherwise fail the test for a reason
        unrelated to explicit placement.
        """
        leaves = await client.filters(kind=NetworkDevice, branch=SERVER_BRANCH, role__value="leaf", include=["rack"])
        assert leaves, "no leaf devices; the cascade did not run"

        for leaf in leaves:
            ports = await client.filters(
                kind=NetworkInterface,
                branch=SERVER_BRANCH,
                device__ids=[leaf.id],
                role__value="server",
                include=["ip_address", "link"],
            )
            free = next((port for port in ports if port.link.id is None and port.ip_address.id is None), None)
            if free is not None and leaf.rack.id is not None:
                return leaf, free

        pytest.fail("no leaf has a free role:server port; explicit placement cannot be exercised")

    @staticmethod
    async def _occupied_server_port(client: InfrahubClient) -> NetworkInterface:
        """Return an already-cabled ``role:server`` leaf port."""
        leaves = await client.filters(kind=NetworkDevice, branch=SERVER_BRANCH, role__value="leaf")
        assert leaves, "no leaf devices; the cascade did not run"

        for leaf in leaves:
            ports = await client.filters(
                kind=NetworkInterface,
                branch=SERVER_BRANCH,
                device__ids=[leaf.id],
                role__value="server",
                include=["ip_address", "link"],
            )
            occupied = next(
                (port for port in ports if port.link.id is not None or port.ip_address.id is not None), None
            )
            if occupied is not None:
                return occupied

        pytest.fail("no role:server port is occupied; the seed journeys did not cable anything")
