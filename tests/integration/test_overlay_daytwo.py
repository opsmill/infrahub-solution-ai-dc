"""Integration test for US2: scoped day-two regeneration of the EVPN/VXLAN overlay.

Encodes quickstart.md §5: after the overlay is generated, adding a segment to a tenant must
reconfigure *only* the carrying leafs. Spines and super-spines carry no tenant state at all, so a new
segment cannot reach their configuration (SC-003, SC-006, FR-007, FR-009).

This test was skipped from the day it was written, because its assertions need leaf devices and the
suite had no way to build them. It now drives the real cascade via ``tests/integration/cascade.py``
(see ``test_provision_cascade``), which is why the two things that kept the cascade from firing are
handled explicitly:

* ``triggers.yml`` is loaded by neither ``inv load`` nor repository sync, so it is loaded directly.
* Every rule is ``branch_scope: other_branches``, so nothing can cascade on ``main``. Every assertion
  below runs on ``OVERLAY_BRANCH``.

Scoping is asserted on ``NetworkDevice.segments`` rather than by byte-comparing rendered
``startup_configuration`` artifacts, which is what the original draft attempted. Measured against a
live 1.11.0b1 stack: no ``Startup configuration`` artifact exists for *any* device. The four
per-vendor artifact_definitions are imported and the devices do join their ``{vendor}_devices`` group,
but nothing in the platform generates those artifacts on group membership, and ``artifact_generate``
only regenerates an artifact that already exists -- both it and ``artifact_fetch`` raise
``NodeNotFoundError``. The only artifacts present on either branch are ``Cabling Plan`` and ``Cilium
BGP Manifest``. An artifact assertion here would therefore be testing artifact scheduling, not
scoping; ``segments`` is the state the render reads, so asserting it tests the property directly and
cannot pass vacuously.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from infrahub_sdk.protocols import CoreGenericRepository
from infrahub_sdk.testing.docker import TestInfrahubDockerClient
from infrahub_sdk.testing.repository import GitRepo

from infrahub_solution_ai_dc.protocols import NetworkDevice, NetworkSegment, NetworkTenant, NetworkVrf
from tests.integration.cascade import (
    GENERATOR_TIMEOUT,
    load_trigger_rules,
    provision_fabric_cascade,
    run_generator,
    wait_until,
)

if TYPE_CHECKING:
    from pathlib import Path

    from infrahub_sdk import InfrahubClient

# Standard groups the generator definitions target; "tenants" drives the OverlayGenerator.
REQUIRED_GROUPS = ["halls", "racks", "fabrics", "pods", "devices", "tenants"]

# Every rule in triggers.yml is branch_scope: other_branches, so the cascade cannot run on main.
OVERLAY_BRANCH = "overlay-daytwo-test"

# Seed tenant topology (objects/12_overlay.yml). The seed already carries advertise-all routed
# segments; this test adds one more and asserts scoped regeneration.
TENANT_NAME = "Blue"
VRF_NAME = "blue-prod"
NEW_SEGMENT_NAME = "blue-extra"

# Roles that must never carry tenant state, whatever happens to a tenant.
TENANT_FREE_ROLES = ("spine", "super_spine")


async def generate_tenant(client: InfrahubClient) -> None:
    """Run ``generate-tenant`` for the seed tenant.

    Only ``Blue`` is generated: ``objects/12_overlay.yml`` also seeds ``Green`` on Fabric-D, and this
    suite cascades Fabric-A only, so generating Green would fail for want of leaves.

    The generator is invoked explicitly rather than by touching the tenant and waiting for a trigger:
    a ``save()`` that changes no field writes nothing and emits no NodeUpdatedEvent, so it dispatches
    nothing at all.
    """
    tenant = await client.get(kind=NetworkTenant, branch=OVERLAY_BRANCH, name__value=TENANT_NAME)
    await run_generator(
        client, definition_name="generate-tenant", branch=OVERLAY_BRANCH, node_ids=[tenant.id]
    )


async def leaves_with_segments(client: InfrahubClient) -> list[NetworkDevice]:
    """Return the leaf devices that carry at least one segment."""
    leaves = await client.filters(
        kind=NetworkDevice, branch=OVERLAY_BRANCH, role__value="leaf", include=["segments"]
    )
    return [leaf for leaf in leaves if leaf.segments.peers]


def segment_names(device: NetworkDevice) -> set[str]:
    """The set of segment display labels materialized onto a device."""
    return {peer.display_label for peer in device.segments.peers if peer.display_label}


class TestOverlayDayTwo(TestInfrahubDockerClient):
    """US2 — adding a segment reconfigures only the carrying leafs."""

    # --- setup -----------------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_load_schema(self, default_branch: str, client: InfrahubClient, schemas: list[dict]) -> None:
        """Load the overlay-extended schemas and wait for convergence."""
        await client.schema.wait_until_converged(branch=default_branch)

        resp = await client.schema.load(schemas=schemas, branch=default_branch, wait_until_converged=True)
        assert resp.errors == {}

    @pytest.mark.asyncio
    async def test_create_groups(self, client: InfrahubClient) -> None:
        """Create the CoreStandardGroup objects the generator definitions target, incl. "tenants"."""
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
        """Register and sync this repo, seeding the overlay objects the same way ``inv load`` does."""
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
        """Build the fabric the overlay is placed on: fabric -> pod -> rack, on a non-default branch.

        Asserted as its own phase so a cascade failure is reported as such, rather than surfacing
        later as a puzzling "expected at least one leaf device".
        """
        await client.branch.create(branch_name=OVERLAY_BRANCH, sync_with_git=False)
        await provision_fabric_cascade(client, branch=OVERLAY_BRANCH)

        leaves = await client.count(kind=NetworkDevice, branch=OVERLAY_BRANCH, role__value="leaf")
        assert leaves, "the cascade produced no leaf devices; the overlay has nowhere to land"

    @pytest.mark.asyncio
    async def test_overlay_materializes_on_leaves(self, client: InfrahubClient) -> None:
        """The OverlayGenerator must place the seed tenant's segments onto leaves.

        The precondition for the scoping test below, asserted separately: "no segment moved" and "the
        generator never ran" are different failures with the same symptom.
        """
        await generate_tenant(client)

        carrying: list[NetworkDevice] = []

        async def segments_materialized() -> bool:
            carrying.clear()
            carrying.extend(await leaves_with_segments(client))
            return bool(carrying)

        await wait_until(
            segments_materialized,
            what=f"tenant {TENANT_NAME} segments materialized onto at least one leaf",
            timeout_seconds=GENERATOR_TIMEOUT,
        )

    # --- the scoping property --------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_spines_carry_no_tenant_state(self, client: InfrahubClient) -> None:
        """SC-006 / FR-007: spines and super-spines hold no segments at all.

        This is the structural reason scoped regeneration holds: a tenant change cannot reach a device
        that carries no tenant state in the first place. Asserted before the day-two change so the
        test below can prove the property *survives* one.
        """
        for role in TENANT_FREE_ROLES:
            devices = await client.filters(
                kind=NetworkDevice, branch=OVERLAY_BRANCH, role__value=role, include=["segments"]
            )
            assert devices, f"no {role} devices were built; this assertion would pass vacuously"
            for device in devices:
                assert not device.segments.peers, (
                    f"{role} {device.hostname.value} carries segments "
                    f"({sorted(segment_names(device))}); tenant state must never reach a {role}"
                )

    @pytest.mark.asyncio
    async def test_scoped_regeneration(self, client: InfrahubClient) -> None:
        """SC-003 / FR-009: adding a segment changes the carrying leafs and nothing else.

        Flow:
          1. Snapshot every leaf's segment set, and confirm the spines are tenant-free.
          2. Add a routed segment with no rack placement (advertise-all).
          3. Re-run the OverlayGenerator and wait for the new segment to land on a carrying leaf.
          4. Assert the carrying leaves gained exactly that segment and lost nothing, and that the
             spines and super-spines are *still* tenant-free.
        """
        before = {leaf.id: segment_names(leaf) for leaf in await leaves_with_segments(client)}
        assert before, "no leaf carries segments; test_overlay_materializes_on_leaves should have failed first"

        # --- day-two change: a third routed segment, advertise-all (no racks) --------------------
        vrf = await client.get(kind=NetworkVrf, branch=OVERLAY_BRANCH, name__value=VRF_NAME)
        new_segment = await client.create(
            kind=NetworkSegment,
            branch=OVERLAY_BRANCH,
            name=NEW_SEGMENT_NAME,
            vrf=vrf.id,
            routed=True,
        )
        await new_segment.save()

        await generate_tenant(client)

        # --- wait for the new segment to be materialized -----------------------------------------
        async def new_segment_landed() -> bool:
            carrying = await leaves_with_segments(client)
            return any(NEW_SEGMENT_NAME in segment_names(leaf) for leaf in carrying)

        await wait_until(
            new_segment_landed,
            what=f"segment {NEW_SEGMENT_NAME!r} materialized onto a carrying leaf",
            timeout_seconds=GENERATOR_TIMEOUT,
        )

        # --- the carrying leaves gained the segment and lost nothing -----------------------------
        after = {leaf.id: segment_names(leaf) for leaf in await leaves_with_segments(client)}
        gained = [leaf_id for leaf_id, names in after.items() if NEW_SEGMENT_NAME in names]
        assert gained, f"no leaf gained {NEW_SEGMENT_NAME!r}"

        for leaf_id, names_before in before.items():
            names_after = after.get(leaf_id, set())
            assert names_before <= names_after, (
                f"leaf {leaf_id} lost segments {sorted(names_before - names_after)} when a segment was added; "
                "regeneration is destructive, not additive"
            )

        # --- and the scoping property still holds ------------------------------------------------
        for role in TENANT_FREE_ROLES:
            devices = await client.filters(
                kind=NetworkDevice, branch=OVERLAY_BRANCH, role__value=role, include=["segments"]
            )
            for device in devices:
                assert not device.segments.peers, (
                    f"{role} {device.hostname.value} gained segments {sorted(segment_names(device))} after a "
                    "tenant change; scoped regeneration is violated (SC-003/FR-009)"
                )
