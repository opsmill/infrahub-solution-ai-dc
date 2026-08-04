"""Integration coverage for the fabric -> pod -> rack generator trigger chain.

Reported against 1.11.0b0: "the generators between the fabric, pods, and racks don't seem to be
triggering consistently ... only part of the chain runs, especially from fabric -> pod and
pod -> rack". Nothing under ``tests/integration`` exercised that chain, so the failure had no
regression net. This module builds one.

The chain is not one generator. It is three, stitched together by a side-effect checksum write
plus the ``CoreNodeTriggerRule`` objects in ``triggers.yml``::

    FabricGenerator  -- writes NetworkPod.checksum ------> generate_fabric.py:152
      trigger-pod-generator-update-checksum                triggers.yml
    PodGenerator     -- writes LocationRack.checksum ----> generate_pod.py
      trigger-rack-generator-update-checksum               triggers.yml
    RackGenerator    -- terminal, writes no checksum

Two facts make this chain impossible to cover by accident, and both are encoded below because
each one silently truncates the cascade:

1. ``triggers.yml`` is loaded by neither ``inv load`` (tasks.py) nor repository sync -- it is a
   manual step (AGENTS.md). Without ``test_load_trigger_rules`` there are no trigger rules at
   all and the cascade stops dead after the fabric tier, with no error anywhere.
2. Every rule in ``triggers.yml`` sets ``branch_scope: other_branches``, which the platform
   compiles to an event match of ``infrahub.branch.name != <default_branch>`` (see
   ``backend/infrahub/actions/models.py``, ``_from_node_trigger``). The cascade therefore cannot
   fire on ``main`` at all. These tests run on a dedicated branch, and
   ``test_default_branch_does_not_cascade`` pins that asymmetry so it is a documented property
   rather than a surprise.

Runtime note: the seed topology (``objects/10_fabric.yml``) is used as-is rather than a smaller
purpose-built fabric, because the cabling helpers are only proven against these device
templates. Only Fabric-A is driven, but the cascade still builds 6 super-spines, 2 pods of
spines and every Pod-A rack, so expect this module to run in minutes, not seconds. Every wait is
condition-based with an env-overridable ceiling -- no fixed sleeps standing in for convergence.
"""

from __future__ import annotations

import asyncio
import os
import time
from typing import TYPE_CHECKING

import pytest
from infrahub_sdk.protocols import (
    CoreGeneratorAction,
    CoreGeneratorDefinition,
    CoreGenericRepository,
    CoreNodeTriggerRule,
)
from infrahub_sdk.spec.object import ObjectFile
from infrahub_sdk.testing.docker import TestInfrahubDockerClient
from infrahub_sdk.testing.repository import GitRepo

from infrahub_solution_ai_dc.protocols import (
    LocationRack,
    NetworkDevice,
    NetworkFabric,
    NetworkInterface,
    NetworkPod,
    TemplateNetworkDevice,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from pathlib import Path

    from infrahub_sdk import InfrahubClient

# Mirrors tests/integration/test_infrahub.py. The remaining groups (server_services,
# kubernetes_clusters, per-vendor device groups) arrive with objects/01_groups.yml during
# repository sync.
REQUIRED_GROUPS = ["halls", "racks", "fabrics", "pods", "devices", "tenants"]

# The cascade cannot fire on the default branch (branch_scope: other_branches), so all chain
# assertions run here.
CHAIN_BRANCH = "generator-chain-test"

# Fabric-A from objects/10_fabric.yml: 6 super-spines, one role="fabric" pod holding them
# (Pod-A1) plus two generated pods (Pod-A2, Pod-A3), each with its own racks.
FABRIC_NAME = "Fabric-A"
FABRIC_POD_ROLE = "fabric"

# Ceilings, not expected durations: each wait returns as soon as its condition holds.
FABRIC_TIER_TIMEOUT = float(os.environ.get("AI_DC_FABRIC_TIER_TIMEOUT", "600"))
POD_TIER_TIMEOUT = float(os.environ.get("AI_DC_POD_TIER_TIMEOUT", "900"))
RACK_TIER_TIMEOUT = float(os.environ.get("AI_DC_RACK_TIER_TIMEOUT", "1200"))
# How long to watch for a cascade that must NOT happen. Bounded on purpose: a negative
# assertion can only ever be "nothing within this window".
NO_CASCADE_WINDOW = float(os.environ.get("AI_DC_NO_CASCADE_WINDOW", "120"))
# Ceiling for the two xfail gap tests below. Deliberately much tighter than the tier timeouts:
# timing out IS the expected path today, so a generous ceiling buys nothing and costs that much
# wall-clock on every run. It only needs to be long enough to build ONE extra device, so that
# adding the missing trigger rule turns the test green (strict xfail then fails the run and forces
# the marker off) rather than still timing out and hiding the fix.
GAP_TIMEOUT = float(os.environ.get("AI_DC_GAP_TIMEOUT", "300"))
POLL_INTERVAL = 5.0

# wait_until_completion is false so a long generator run cannot trip the client HTTP timeout;
# the tests poll the resulting data instead. Registered as CoreGeneratorDefinitionRun
# (backend/infrahub/graphql/schema.py).
RUN_GENERATOR_MUTATION = """
mutation RunGenerator($id: String!, $nodes: [String!]) {
  CoreGeneratorDefinitionRun(data: {id: $id, nodes: $nodes}, wait_until_completion: false) {
    ok
    task { id }
  }
}
"""


async def wait_until(
    predicate: Callable[[], Awaitable[bool]],
    *,
    what: str,
    timeout_seconds: float,
    interval: float = POLL_INTERVAL,
) -> None:
    """Poll ``predicate`` until it holds, failing with a named message on timeout."""
    deadline = time.monotonic() + timeout_seconds
    while True:
        if await predicate():
            return
        if time.monotonic() >= deadline:
            pytest.fail(f"timed out after {timeout_seconds:.0f}s waiting for {what}")
        await asyncio.sleep(interval)


async def stays_false(
    predicate: Callable[[], Awaitable[bool]],
    *,
    window: float,
    interval: float = POLL_INTERVAL,
) -> bool:
    """Return True when ``predicate`` never holds for the whole ``window``."""
    deadline = time.monotonic() + window
    while time.monotonic() < deadline:
        if await predicate():
            return False
        await asyncio.sleep(interval)
    return True


async def run_generator(
    client: InfrahubClient,
    *,
    definition_name: str,
    branch: str,
    node_ids: list[str],
) -> None:
    """Submit a generator definition run for specific targets, without waiting for completion."""
    definition = await client.get(kind=CoreGeneratorDefinition, name__value=definition_name, branch=branch)
    result = await client.execute_graphql(
        query=RUN_GENERATOR_MUTATION,
        variables={"id": definition.id, "nodes": node_ids},
        branch_name=branch,
    )
    assert result["CoreGeneratorDefinitionRun"]["ok"] is True


async def count_devices_in_pod(client: InfrahubClient, *, branch: str, pod_id: str, role: str) -> int:
    """Count the devices of a given role attached to a pod."""
    devices = await client.filters(kind=NetworkDevice, branch=branch, pod__ids=[pod_id], role__value=role)
    return len(devices)


async def count_leaves_in_rack(client: InfrahubClient, *, branch: str, rack_id: str) -> int:
    """Count the leaf devices attached to a rack."""
    devices = await client.filters(kind=NetworkDevice, branch=branch, rack__ids=[rack_id], role__value="leaf")
    return len(devices)


async def get_fabric_pods(client: InfrahubClient, *, branch: str, fabric_id: str) -> list[NetworkPod]:
    """Return every pod of a fabric, including the role="fabric" pod that holds the super-spines."""
    return await client.filters(kind=NetworkPod, branch=branch, parent__ids=[fabric_id])


def generated_pods(pods: list[NetworkPod]) -> list[NetworkPod]:
    """Filter out the role="fabric" pod, which PodGenerator skips (EXCLUDED_POD_ROLES)."""
    return [pod for pod in pods if pod.role.value != FABRIC_POD_ROLE]


class TestGeneratorTriggerChain(TestInfrahubDockerClient):
    """fabric -> pod -> rack must complete end to end, driven only by trigger rules."""

    @pytest.mark.asyncio
    async def test_load_schema(self, default_branch: str, client: InfrahubClient, schemas: list[dict]) -> None:
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
        root_directory: Path,
    ) -> None:
        """Register and sync this repo: generator definitions, queries and the objects/ seed."""
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
    async def test_seed_topology_present(self, client: InfrahubClient, default_branch: str) -> None:
        """Repository sync must have seeded the fabric/pod/rack topology the chain walks.

        Guards the tests below from reporting a broken cascade when the real problem is that
        objects/ never loaded.
        """
        fabric = await client.get(kind=NetworkFabric, name__value=FABRIC_NAME, branch=default_branch)
        assert fabric.amount_of_super_spines.value

        pods = await get_fabric_pods(client, branch=default_branch, fabric_id=fabric.id)
        assert generated_pods(pods), f"{FABRIC_NAME} has no non-fabric pods to cascade into"

        racks = await client.filters(
            kind=LocationRack,
            branch=default_branch,
            pod__ids=[pod.id for pod in generated_pods(pods)],
        )
        assert racks, f"{FABRIC_NAME} pods have no racks to cascade into"

    @pytest.mark.asyncio
    async def test_load_trigger_rules(self, client: InfrahubClient, root_directory: Path) -> None:
        """Load triggers.yml -- the step neither ``inv load`` nor repository sync performs.

        Loaded after repository sync on purpose: each CoreGeneratorAction references a generator
        definition by name, which only exists once the repo has been imported.
        """
        trigger_files = ObjectFile.load_from_disk(paths=[root_directory / "triggers.yml"])
        assert trigger_files, "triggers.yml produced no object documents"

        for trigger_file in trigger_files:
            trigger_file.validate_content()
            await trigger_file.process(client=client)

        actions = await client.all(kind=CoreGeneratorAction)
        assert {action.name.value for action in actions} >= {
            "run-pod-generator",
            "run-rack-generator",
        }, "the pod/rack generator actions are missing; the cascade cannot dispatch"

        rules = await client.all(kind=CoreNodeTriggerRule)
        assert {"NetworkPod", "LocationRack"} <= {rule.node_kind.value for rule in rules}, (
            "no trigger rules for NetworkPod/LocationRack; fabric -> pod -> rack cannot fire"
        )

    @pytest.mark.asyncio
    async def test_create_chain_branch(self, client: InfrahubClient) -> None:
        """Create the branch the cascade runs on (branch_scope: other_branches excludes main)."""
        await client.branch.create(branch_name=CHAIN_BRANCH, sync_with_git=False)

        branches = await client.branch.all()
        assert CHAIN_BRANCH in branches

    @pytest.mark.asyncio
    async def test_fabric_tier_materializes(self, client: InfrahubClient) -> None:
        """Tier 1: running generate-fabric builds every super-spine.

        This is the only generator invoked explicitly. Everything after it must arrive by
        trigger alone -- that is the property under test.
        """
        fabric = await client.get(kind=NetworkFabric, name__value=FABRIC_NAME, branch=CHAIN_BRANCH)
        expected = fabric.amount_of_super_spines.value
        fabric_pod = await client.get(
            kind=NetworkPod, branch=CHAIN_BRANCH, parent__ids=[fabric.id], role__value=FABRIC_POD_ROLE
        )

        await run_generator(client, definition_name="generate-fabric", branch=CHAIN_BRANCH, node_ids=[fabric.id])

        async def super_spines_ready() -> bool:
            count = await count_devices_in_pod(client, branch=CHAIN_BRANCH, pod_id=fabric_pod.id, role="super_spine")
            return count >= expected

        await wait_until(
            super_spines_ready,
            what=f"{expected} super-spine devices in {FABRIC_NAME}",
            timeout_seconds=FABRIC_TIER_TIMEOUT,
        )

    @pytest.mark.asyncio
    async def test_fabric_stamps_pod_checksums(self, client: InfrahubClient) -> None:
        """The cascade's carrier: the fabric generator must stamp every pod's checksum.

        Asserted separately from the pod tier because these are distinct failures with the same
        symptom. An unstamped pod means the fabric generator never reached update_checksum
        (generate_fabric.py:152, called after allocate_resource_pools/create_super_spine_switches
        -- any failure in those aborts the cascade). A stamped pod with no spines means the stamp
        landed but the trigger did not dispatch.
        """
        fabric = await client.get(kind=NetworkFabric, name__value=FABRIC_NAME, branch=CHAIN_BRANCH)
        pods = await get_fabric_pods(client, branch=CHAIN_BRANCH, fabric_id=fabric.id)

        async def all_pods_stamped() -> bool:
            current = await get_fabric_pods(client, branch=CHAIN_BRANCH, fabric_id=fabric.id)
            return all(pod.checksum.value for pod in current)

        await wait_until(
            all_pods_stamped,
            what=f"a checksum stamp on all {len(pods)} pods of {FABRIC_NAME}",
            timeout_seconds=FABRIC_TIER_TIMEOUT,
        )

    @pytest.mark.asyncio
    async def test_pod_tier_is_triggered_by_fabric(self, client: InfrahubClient) -> None:
        """Tier 2, the reported break: every non-fabric pod gets its spines, by trigger only.

        No generator is invoked here. The spines may only appear because the pod checksum stamp
        fired trigger-pod-generator-update-checksum.
        """
        fabric = await client.get(kind=NetworkFabric, name__value=FABRIC_NAME, branch=CHAIN_BRANCH)
        pods = generated_pods(await get_fabric_pods(client, branch=CHAIN_BRANCH, fabric_id=fabric.id))
        assert pods

        for pod in pods:
            expected = pod.amount_of_spines.value

            async def spines_ready(pod_id: str = pod.id, expected: int = expected) -> bool:
                count = await count_devices_in_pod(client, branch=CHAIN_BRANCH, pod_id=pod_id, role="spine")
                return count >= expected

            await wait_until(
                spines_ready,
                what=f"{expected} spine devices in pod {pod.name.value} (fabric -> pod trigger)",
                timeout_seconds=POD_TIER_TIMEOUT,
            )

    @pytest.mark.asyncio
    async def test_rack_tier_is_triggered_by_pod(self, client: InfrahubClient) -> None:
        """Tier 3, the reported break: every rack gets its leaves, by trigger only.

        Again no generator is invoked: the leaves may only appear because each pod generator
        stamped its racks' checksums and trigger-rack-generator-update-checksum dispatched.
        """
        fabric = await client.get(kind=NetworkFabric, name__value=FABRIC_NAME, branch=CHAIN_BRANCH)
        pods = generated_pods(await get_fabric_pods(client, branch=CHAIN_BRANCH, fabric_id=fabric.id))
        racks = await client.filters(kind=LocationRack, branch=CHAIN_BRANCH, pod__ids=[pod.id for pod in pods])
        assert racks

        for rack in racks:
            expected = rack.amount_of_leafs.value

            async def leaves_ready(rack_id: str = rack.id, expected: int = expected) -> bool:
                count = await count_leaves_in_rack(client, branch=CHAIN_BRANCH, rack_id=rack_id)
                return count >= expected

            await wait_until(
                leaves_ready,
                what=f"{expected} leaf devices in rack {rack.name.value} (pod -> rack trigger)",
                timeout_seconds=RACK_TIER_TIMEOUT,
            )

    @pytest.mark.asyncio
    async def test_rerunning_upstream_does_not_restamp(self, client: InfrahubClient) -> None:
        """Characterises the latch that makes a broken chain unrecoverable.

        Re-running the fabric generator recomputes the same checksum from the same related ids
        (GeneratorMixin.calculate_checksum), so the ``if pod.checksum.value != fabric_checksum``
        guard in generate_fabric.py:158 writes nothing and no NodeUpdatedEvent is emitted.

        Idempotence is the intent, and this test asserts it. The defect is what the same
        behaviour does after a downstream failure: the pod is already stamped, so re-running the
        fabric generator cannot re-dispatch the pod generator, and the tier stays broken
        permanently. Recovery today means clearing the checksum by hand. That is the mechanism
        behind "only part of the chain runs" being persistent rather than intermittent -- and it
        is why a fix needs an explicit re-dispatch path (or a generator-instance success check)
        rather than relying on a value change.
        """
        fabric = await client.get(kind=NetworkFabric, name__value=FABRIC_NAME, branch=CHAIN_BRANCH)
        before = {
            pod.id: pod.checksum.value
            for pod in await get_fabric_pods(client, branch=CHAIN_BRANCH, fabric_id=fabric.id)
        }
        assert any(before.values()), "no pod carried a checksum; the fabric tier never completed"

        await run_generator(client, definition_name="generate-fabric", branch=CHAIN_BRANCH, node_ids=[fabric.id])

        async def any_checksum_changed() -> bool:
            current = await get_fabric_pods(client, branch=CHAIN_BRANCH, fabric_id=fabric.id)
            return any(pod.checksum.value != before.get(pod.id) for pod in current)

        assert await stays_false(any_checksum_changed, window=NO_CASCADE_WINDOW), (
            "a pod checksum changed on an unchanged re-run; the cascade would re-fire on every fabric generator run"
        )

    @pytest.mark.asyncio
    async def test_default_branch_does_not_cascade(self, client: InfrahubClient, default_branch: str) -> None:
        """Pins branch_scope: every rule is other_branches, so main never cascades.

        Running the fabric generator on main builds super-spines (the generator is invoked
        directly) but must produce no spines, because the pod checksum stamp emits an event that
        no automation matches -- ``_from_node_trigger`` compiles other_branches to
        ``infrahub.branch.name != main``.

        This is current intended configuration, not a bug, but it is the first thing to rule out
        when the chain "does not trigger": a load driven on main can only ever build tier 1.
        """
        fabric = await client.get(kind=NetworkFabric, name__value=FABRIC_NAME, branch=default_branch)
        all_pods = await get_fabric_pods(client, branch=default_branch, fabric_id=fabric.id)
        pods = generated_pods(all_pods)
        assert pods
        fabric_pod = next(pod for pod in all_pods if pod.role.value == FABRIC_POD_ROLE)

        await run_generator(client, definition_name="generate-fabric", branch=default_branch, node_ids=[fabric.id])

        # Control 1: the generator really did run here. Without this, "no spines" is ambiguous --
        # a generator that crashed on startup would produce the same emptiness and the test would
        # pass while proving nothing about branch_scope.
        async def super_spines_on_default() -> bool:
            count = await count_devices_in_pod(client, branch=default_branch, pod_id=fabric_pod.id, role="super_spine")
            return count >= fabric.amount_of_super_spines.value

        await wait_until(
            super_spines_on_default,
            what=f"super-spines on {default_branch} (proving the generator ran there at all)",
            timeout_seconds=FABRIC_TIER_TIMEOUT,
        )

        # Control 2: the trigger's precondition was satisfied -- the pods carry a checksum, so a
        # NodeUpdatedEvent was emitted on the default branch. Anything that does not happen next
        # is therefore down to the event not matching, not to the event never existing.
        async def pods_stamped_on_default() -> bool:
            current = await get_fabric_pods(client, branch=default_branch, fabric_id=fabric.id)
            return all(pod.checksum.value for pod in current)

        await wait_until(
            pods_stamped_on_default,
            what=f"pod checksum stamps on {default_branch} (the trigger's precondition)",
            timeout_seconds=FABRIC_TIER_TIMEOUT,
        )

        # The actual assertion: stamped pods, emitted events, and still no pod generator ran.
        async def any_spine_on_default() -> bool:
            for pod in pods:
                if await count_devices_in_pod(client, branch=default_branch, pod_id=pod.id, role="spine"):
                    return True
            return False

        assert await stays_false(any_spine_on_default, window=NO_CASCADE_WINDOW), (
            "spines appeared on the default branch; branch_scope: other_branches is not being "
            "honoured and triggers.yml no longer describes actual behaviour"
        )

    @pytest.mark.asyncio
    async def test_cascade_stamps_vendor_groups(self, client: InfrahubClient) -> None:
        """Every device the cascade built must join its manufacturer's {vendor}_devices group.

        Membership is stamped by the generators themselves (``vendor_group_for_template``), and
        the per-vendor startup-config artifacts target these groups -- an unstamped device renders
        no config at all. Fabric-A is the Cisco fabric (objects/10_fabric.yml).
        """
        vendor_group = await client.get(kind="CoreStandardGroup", name__value="cisco_devices", branch=CHAIN_BRANCH)

        for role in ("super_spine", "spine", "leaf"):
            devices = await client.filters(
                kind=NetworkDevice,
                branch=CHAIN_BRANCH,
                role__value=role,
                member_of_groups__ids=[vendor_group.id],
            )
            assert devices, f"no {role} device joined cisco_devices; the vendor artifacts will render nothing"

    @pytest.mark.asyncio
    async def test_cascade_leaves_are_fully_wired(self, client: InfrahubClient) -> None:
        """A leaf the cascade built must be complete, not half-built.

        "The tier ran" and "the tier finished its work" are different claims, and only the second
        one matters downstream -- a leaf with no loopback or no P2P addressing renders a broken
        startup config. Two invariants cover it:

        * ``loopback_ip`` is set, which happens during ``create_leaf_switches``.
        * every spine-facing interface carries an ip_address. Those /31s come from
          ``assign_ip_addresses_to_p2p_connections``, which runs only after
          ``connect_leafs_to_spine`` has cabled the interfaces -- so an addressed
          spine-facing interface proves cabling *and* addressing both completed.

        Asserted structurally rather than by rendering an artifact: ``artifact_generate`` only
        regenerates an artifact that already exists, and nothing in the platform generates the
        per-vendor startup configs automatically on group membership, so an artifact assertion
        here would be testing artifact scheduling rather than the cascade.
        """
        fabric = await client.get(kind=NetworkFabric, name__value=FABRIC_NAME, branch=CHAIN_BRANCH)
        pods = generated_pods(await get_fabric_pods(client, branch=CHAIN_BRANCH, fabric_id=fabric.id))
        assert pods

        pod = pods[0]
        leaves = await client.filters(
            kind=NetworkDevice,
            branch=CHAIN_BRANCH,
            pod__ids=[pod.id],
            role__value="leaf",
            include=["loopback_ip"],
        )
        assert leaves, f"the rack tier never completed for pod {pod.name.value}"

        expected_uplinks = pod.amount_of_spines.value
        for leaf in leaves:
            assert leaf.loopback_ip.id, f"leaf {leaf.hostname.value} has no loopback IP"

            uplinks = await client.filters(
                kind=NetworkInterface,
                branch=CHAIN_BRANCH,
                device__ids=[leaf.id],
                role__value="spine",
                include=["ip_address"],
            )
            addressed = [interface for interface in uplinks if interface.ip_address.id]
            assert len(addressed) == expected_uplinks, (
                f"leaf {leaf.hostname.value} has {len(addressed)} addressed spine-facing interfaces, "
                f"expected {expected_uplinks} -- the rack generator did not finish cabling/addressing"
            )

    # Everything above asserts the cascade's steady state. Everything from here on MUTATES the
    # topology, so it must stay below: an earlier `amount_of_spines` bump leaves the leaves
    # cabled against the old spine count until the rack generators catch up, which turned
    # test_cascade_leaves_are_fully_wired into a race when this test ran before it.
    @pytest.mark.asyncio
    async def test_pod_spine_count_change_regenerates(self, client: InfrahubClient) -> None:
        """A watched non-checksum attribute must dispatch: amount_of_spines has a rule.

        The highest-signal test for comparing 1.10.6 against 1.11.0b0. Unlike the checksum
        relay, this exercises ``CoreNodeTriggerAttributeMatch`` on an ordinary attribute
        end-to-end: the mutation's changelog has to surface an ``infrahub.node.attribute_update``
        related resource carrying ``infrahub.field.name = amount_of_spines`` for the automation to
        match (see ``events/node_action.py`` ``get_related``). If this passes on 1.10.6 and fails
        on 1.11.0b0, the regression is in event emission or matching, not in this repo.
        """
        fabric = await client.get(kind=NetworkFabric, name__value=FABRIC_NAME, branch=CHAIN_BRANCH)
        pods = generated_pods(await get_fabric_pods(client, branch=CHAIN_BRANCH, fabric_id=fabric.id))
        assert pods

        pod = pods[0]
        target = pod.amount_of_spines.value + 1
        pod.amount_of_spines.value = target
        await pod.save()

        async def extra_spine_built() -> bool:
            count = await count_devices_in_pod(client, branch=CHAIN_BRANCH, pod_id=pod.id, role="spine")
            return count >= target

        await wait_until(
            extra_spine_built,
            what=f"{target} spine devices in pod {pod.name.value} after an amount_of_spines change",
            timeout_seconds=POD_TIER_TIMEOUT,
        )

    @pytest.mark.asyncio
    async def test_new_fabric_has_no_automatic_dispatch(self, client: InfrahubClient) -> None:
        """The chain has no automatic entry point -- creating a fabric starts nothing.

        This is the most consequential finding behind the report, and it is configuration, not a
        platform bug. ``generate-fabric`` has four possible dispatch paths and this repo closes
        all of them:

        * proposed change -- ``.infrahub.yml`` sets ``execute_in_proposed_change: false``, and
          ``generators/tasks.py:154`` skips the definition for that source.
        * after merge -- ``execute_after_merge: false``, skipped at ``generators/tasks.py:155``
          and again in ``core/merge/selective_regen/.../generator_selector.py:34``.
        * group membership -- ``GroupMemberAddedEvent`` is only consumed by a
          ``CoreGroupTriggerRule``, and ``triggers.yml`` defines none (only
          ``CoreNodeTriggerRule``). ``trigger/catalogue.py``'s ``builtin_triggers`` has no
          generator entry either.
        * node trigger rule -- ``triggers.yml`` has no ``NetworkFabric`` rule at all.

        So the only way to start the cascade is the manual ``CoreGeneratorDefinitionRun``
        mutation (what ``test_fabric_tier_materializes`` does) or ``infrahubctl generator``. Since
        every downstream tier hangs off the fabric generator's checksum stamp, nothing whatsoever
        happens automatically when a fabric is created or resized.

        Asserted as current behaviour so that wiring up any dispatch path fails this test loudly
        and forces a decision, rather than changing the operating model by surprise.
        """
        template = await client.get(
            kind=TemplateNetworkDevice,
            template_name__value="cisco-9364d-gx2-super-spine-switch",
            branch=CHAIN_BRANCH,
        )
        fabric = await client.create(
            kind=NetworkFabric,
            branch=CHAIN_BRANCH,
            name="Fabric-NoDispatch",
            index=99,
            amount_of_super_spines=2,
            super_spine_switch_template=template.id,
            member_of_groups=["fabrics"],
        )
        await fabric.save()

        fabric_pod = await client.create(
            kind=NetworkPod,
            branch=CHAIN_BRANCH,
            name="Pod-NoDispatch-1",
            index=1,
            role=FABRIC_POD_ROLE,
            parent=fabric.id,
            member_of_groups=["pods"],
        )
        await fabric_pod.save()

        async def any_super_spine_built() -> bool:
            count = await count_devices_in_pod(client, branch=CHAIN_BRANCH, pod_id=fabric_pod.id, role="super_spine")
            return count > 0

        assert await stays_false(any_super_spine_built, window=NO_CASCADE_WINDOW), (
            "a new fabric dispatched its generator automatically; one of the four dispatch paths "
            "is now open and the operating model changed -- update this test and triggers.yml docs"
        )

    # --- coverage gaps in triggers.yml -----------------------------------------------------------
    #
    # triggers.yml covers NetworkPod.amount_of_spines but nothing equivalent for the other two
    # tiers: LocationRack.amount_of_leafs has no rule, and NetworkFabric has no rule at all (the
    # file holds 9 rules across NetworkPod, LocationRack, NetworkTenant and NetworkServerService
    # -- there is no NetworkFabric entry). Editing a fabric's super-spine count or a rack's leaf
    # count therefore regenerates nothing, which presents exactly as "the generators don't
    # trigger consistently".
    #
    # Both tests assert the behaviour we want and are strict xfails, so adding the missing rules
    # turns them green and forces the marker off rather than leaving dead coverage behind.

    @pytest.mark.asyncio
    @pytest.mark.xfail(
        strict=True,
        reason="triggers.yml has no LocationRack.amount_of_leafs rule, so a leaf-count edit "
        "never re-runs the rack generator",
    )
    async def test_rack_leaf_count_change_regenerates(self, client: InfrahubClient) -> None:
        """Raising amount_of_leafs on a rack should build the extra leaf."""
        racks = await client.filters(kind=LocationRack, branch=CHAIN_BRANCH)
        rack = next((item for item in racks if item.amount_of_leafs.value), None)
        assert rack is not None, "no rack with a leaf count on the chain branch"

        target = rack.amount_of_leafs.value + 1
        rack.amount_of_leafs.value = target
        await rack.save()

        async def extra_leaf_built() -> bool:
            count = await count_leaves_in_rack(client, branch=CHAIN_BRANCH, rack_id=rack.id)
            return count >= target

        await wait_until(
            extra_leaf_built,
            what=f"{target} leaf devices in rack {rack.name.value} after a leaf-count change",
            timeout_seconds=GAP_TIMEOUT,
        )

    @pytest.mark.asyncio
    @pytest.mark.xfail(
        strict=True,
        reason="triggers.yml has no NetworkFabric rule at all, so a super-spine-count edit "
        "never re-runs the fabric generator",
    )
    async def test_fabric_super_spine_count_change_regenerates(self, client: InfrahubClient) -> None:
        """Raising amount_of_super_spines on a fabric should build the extra super-spine."""
        fabric = await client.get(kind=NetworkFabric, name__value=FABRIC_NAME, branch=CHAIN_BRANCH)
        fabric_pod = await client.get(
            kind=NetworkPod, branch=CHAIN_BRANCH, parent__ids=[fabric.id], role__value=FABRIC_POD_ROLE
        )

        target = fabric.amount_of_super_spines.value + 1
        fabric.amount_of_super_spines.value = target
        await fabric.save()

        async def extra_super_spine_built() -> bool:
            count = await count_devices_in_pod(client, branch=CHAIN_BRANCH, pod_id=fabric_pod.id, role="super_spine")
            return count >= target

        await wait_until(
            extra_super_spine_built,
            what=f"{target} super-spine devices after a super-spine-count change",
            timeout_seconds=GAP_TIMEOUT,
        )
