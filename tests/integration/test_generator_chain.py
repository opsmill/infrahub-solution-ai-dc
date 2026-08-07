"""Integration coverage for the fabric -> pod -> rack generator trigger chain.

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
from collections import Counter
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

# ``LocationRack.amount_of_leafs`` is capped at 2 by the schema (``schemas/physical_location.yml``,
# ``parameters: {min_value: 1, max_value: 2}``). Any test that raises a rack's leaf count has to pick
# a rack with headroom, or the save is rejected by validation before the trigger is ever exercised.
MAX_LEAFS_PER_RACK = 2


def _env_seconds(name: str, default: float) -> float:
    """Read a seconds-valued env override, falling back on anything unparseable.

    Read at import time, so a bare ``float()`` on a typo'd or empty override would raise during
    collection and take the whole module (not just one test) down with a collection error.
    """
    try:
        return float(os.environ[name])
    except (KeyError, ValueError):
        return default


# Ceilings, not expected durations: each wait returns as soon as its condition holds.
FABRIC_TIER_TIMEOUT = _env_seconds("AI_DC_FABRIC_TIER_TIMEOUT", 600)
POD_TIER_TIMEOUT = _env_seconds("AI_DC_POD_TIER_TIMEOUT", 900)
RACK_TIER_TIMEOUT = _env_seconds("AI_DC_RACK_TIER_TIMEOUT", 1200)
# How long to watch for a cascade that must NOT happen. Bounded on purpose: a negative
# assertion can only ever be "nothing within this window".
NO_CASCADE_WINDOW = _env_seconds("AI_DC_NO_CASCADE_WINDOW", 120)
# Ceiling for the two xfail gap tests below. Deliberately much tighter than the tier timeouts:
# timing out IS the expected path today, so a generous ceiling buys nothing and costs that much
# wall-clock on every run. It only needs to be long enough to build ONE extra device, so that
# adding the missing trigger rule turns the test green (strict xfail then fails the run and forces
# the marker off) rather than still timing out and hiding the fix.
GAP_TIMEOUT = _env_seconds("AI_DC_GAP_TIMEOUT", 300)
POLL_INTERVAL = 5.0
# ``wait_until`` polls at this rate for its first ``FAST_POLL_WINDOW`` seconds before settling to
# ``POLL_INTERVAL``, so a condition that is already true is noticed promptly instead of up to 5s
# later. ``stays_false`` deliberately does not use it -- it wants the whole window regardless.
FAST_POLL_INTERVAL = 1.0
FAST_POLL_WINDOW = 15.0

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
    what: str | Callable[[], str],
    timeout_seconds: float,
) -> None:
    """Poll ``predicate`` until it holds, failing with a named message on timeout.

    ``what`` may be a callable, rendered only on timeout, so a predicate that tracks *which* targets
    are still short can report them without paying for the string on every successful wait.

    Polls fast at first, then settles to ``POLL_INTERVAL``. Several waits here converge on their
    first or second poll (the checksum stamps especially), and a flat 5s interval spends up to 5s
    sleeping past a condition that is already true. Polling sooner is never less responsive, so this
    costs nothing and cannot introduce flakiness in either direction.
    """
    deadline = time.monotonic() + timeout_seconds
    fast_until = time.monotonic() + FAST_POLL_WINDOW
    while True:
        if await predicate():
            return
        if time.monotonic() >= deadline:
            message = what() if callable(what) else what
            pytest.fail(f"timed out after {timeout_seconds:.0f}s waiting for {message}")
        await asyncio.sleep(FAST_POLL_INTERVAL if time.monotonic() < fast_until else POLL_INTERVAL)


async def stays_false(predicate: Callable[[], Awaitable[bool]], *, window: float) -> bool:
    """Return True when ``predicate`` never holds for the whole ``window``."""
    deadline = time.monotonic() + window
    while time.monotonic() < deadline:
        if await predicate():
            return False
        await asyncio.sleep(POLL_INTERVAL)
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
    """Count the devices of a given role attached to a pod.

    ``count`` rather than ``filters`` + ``len``: these two helpers are the body of nearly every poll
    in this module, so hundreds of calls per run would otherwise hydrate complete device nodes --
    every attribute and every relationship peer -- purely to discard them and take a length.

    Kept separate from the rack counter rather than merged into one ``**filters`` helper: forwarding
    ``**kwargs`` into the client matches none of its overloads under mypy strict, and the workarounds
    (a ``type: ignore``, or ``**filters: Any`` plus an ANN401 noqa) cost more than the duplicated line.
    """
    return await client.count(kind=NetworkDevice, branch=branch, pod__ids=[pod_id], role__value=role)


async def count_leaves_in_rack(client: InfrahubClient, *, branch: str, rack_id: str) -> int:
    """Count the leaf devices attached to a rack."""
    return await client.count(kind=NetworkDevice, branch=branch, rack__ids=[rack_id], role__value="leaf")


async def get_fabric_pods(client: InfrahubClient, *, branch: str, fabric_id: str) -> list[NetworkPod]:
    """Return every pod of a fabric, including the role="fabric" pod that holds the super-spines."""
    return await client.filters(kind=NetworkPod, branch=branch, parent__ids=[fabric_id])


def generated_pods(pods: list[NetworkPod]) -> list[NetworkPod]:
    """Filter out the role="fabric" pod, which PodGenerator skips (EXCLUDED_POD_ROLES)."""
    return [pod for pod in pods if pod.role.value != FABRIC_POD_ROLE]


async def get_generated_pods(client: InfrahubClient, *, branch: str) -> list[NetworkPod]:
    """Fetch the fabric under test and return only the pods its PodGenerator manages.

    The plain ``get_fabric_pods`` / ``generated_pods`` pair stays available for the tests that need
    the fabric object itself or the unfiltered pod list (the checksum tests, which reuse the fabric
    id inside their predicates, and ``test_default_branch_does_not_cascade``, which needs the
    role="fabric" pod).
    """
    fabric = await client.get(kind=NetworkFabric, name__value=FABRIC_NAME, branch=branch)
    return generated_pods(await get_fabric_pods(client, branch=branch, fabric_id=fabric.id))


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

        generated = generated_pods(await get_fabric_pods(client, branch=default_branch, fabric_id=fabric.id))
        assert generated, f"{FABRIC_NAME} has no non-fabric pods to cascade into"

        racks = await client.filters(
            kind=LocationRack,
            branch=default_branch,
            pod__ids=[pod.id for pod in generated],
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
        pods = await get_generated_pods(client, branch=CHAIN_BRANCH)
        assert pods

        # One wait over ALL pods rather than one per pod: the tiers are dispatched concurrently, so
        # waiting per pod would multiply the ceiling by the pod count (2 pods x 900s = 30 min) while
        # buying nothing -- the last pod to converge sets the wall clock either way.
        async def all_pods_have_spines() -> bool:
            for pod in pods:
                count = await count_devices_in_pod(client, branch=CHAIN_BRANCH, pod_id=pod.id, role="spine")
                if count < pod.amount_of_spines.value:
                    return False
            return True

        await wait_until(
            all_pods_have_spines,
            what=(
                f"spines in every pod of {FABRIC_NAME} (fabric -> pod trigger): "
                + ", ".join(f"{pod.name.value}={pod.amount_of_spines.value}" for pod in pods)
            ),
            timeout_seconds=POD_TIER_TIMEOUT,
        )

    @pytest.mark.asyncio
    async def test_rack_tier_is_triggered_by_pod(self, client: InfrahubClient) -> None:
        """Tier 3, the reported break: every rack gets its leaves, by trigger only.

        Again no generator is invoked: the leaves may only appear because each pod generator
        stamped its racks' checksums and trigger-rack-generator-update-checksum dispatched.
        """
        pods = await get_generated_pods(client, branch=CHAIN_BRANCH)
        racks = await client.filters(kind=LocationRack, branch=CHAIN_BRANCH, pod__ids=[pod.id for pod in pods])
        assert racks

        # One wait over ALL racks, for the same reason as the pod tier: Fabric-A has 8 racks, so a
        # per-rack ceiling would allow 8 x 1200s = 160 min -- more than the whole CI job's
        # timeout-minutes: 60 budget, on a job that also spins three other stacks.
        async def all_racks_have_leaves() -> bool:
            for rack in racks:
                count = await count_leaves_in_rack(client, branch=CHAIN_BRANCH, rack_id=rack.id)
                if count < rack.amount_of_leafs.value:
                    return False
            return True

        await wait_until(
            all_racks_have_leaves,
            what=(
                f"leaf devices in every rack of {FABRIC_NAME} (pod -> rack trigger): "
                + ", ".join(f"{rack.name.value}={rack.amount_of_leafs.value}" for rack in racks)
            ),
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

        Read what this pins narrowly, because it is weaker than it looks in two ways:

        * It pins that the recomputed checksum is the SAME VALUE, i.e. that
          ``calculate_checksum`` is deterministic over an unchanged related-id set. That is the
          load-bearing half of the latch -- a nondeterministic checksum (unsorted ids, a timestamp)
          would re-fire the whole cascade on every run. It does NOT prove the ``!=`` guard exists:
          deleting the guard and writing unconditionally would write the identical value, so no
          value comparison can distinguish the two.
        * ``run_generator`` submits with ``wait_until_completion: false``, and nothing here waits for
          the re-run to reach ``update_checksum`` (it runs last, after pool allocation and six
          super-spine upserts). If the re-run is still in flight when NO_CASCADE_WINDOW closes, the
          window proves nothing at all -- not even determinism. Gating on completion first (a
          synchronous re-run, or waiting on the generator instance) would close that hole; it is
          not done here because a synchronous call risks tripping the client HTTP timeout, which is
          why every other run in this module is submitted async.
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

        # Snapshot BEFORE the run. ``NetworkPod`` is declared ``branch: agnostic``
        # (schemas/logical_design.yml) and ``GeneratorTarget.checksum`` carries no ``branch:``
        # override (schemas/generator.yml), so ``pod.checksum`` holds ONE value across every branch.
        # The chain-branch run above has therefore already stamped every pod as seen from here, and
        # "the pods carry a checksum" proves nothing about what happened on the default branch.
        # Control 2 below has to assert the value CHANGED instead.
        checksums_before = {pod.id: pod.checksum.value for pod in all_pods}

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

        # Control 2: the trigger's precondition was satisfied -- a checksum WRITE landed on the
        # default branch, so a NodeUpdatedEvent was emitted there. Asserted as a change rather than
        # as presence: the default-branch run builds its own super-spines, so
        # GeneratorMixin.calculate_checksum hashes a different set of related ids and the stamp must
        # move. Anything that does not happen next is therefore down to the event not matching,
        # rather than to the event never existing -- which mere presence could not distinguish,
        # since update_checksum runs last and a generator dying before it would leave the
        # branch-agnostic stamp from the chain branch in place.
        async def pod_checksum_changed_on_default() -> bool:
            current = await get_fabric_pods(client, branch=default_branch, fabric_id=fabric.id)
            return any(pod.checksum.value != checksums_before.get(pod.id) for pod in current)

        await wait_until(
            pod_checksum_changed_on_default,
            what=f"a pod checksum write on {default_branch} (the trigger's precondition)",
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
        pods = await get_generated_pods(client, branch=CHAIN_BRANCH)
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

        # Polled, not asserted once. The rack tier's own gate (test_rack_tier_is_triggered_by_pod) is
        # the leaf DEVICE count, which ``create_leaf_switches`` satisfies before
        # ``connect_leafs_to_spine`` has cabled anything and before
        # ``assign_ip_addresses_to_p2p_connections`` has handed out the /31s (generate_rack.py). A
        # bare assertion here therefore passes only on incidental slack from the negative windows
        # above -- and AI_DC_NO_CASCADE_WINDOW is a documented knob, so tuning it down would surface
        # as "the rack generator did not finish cabling/addressing" and blame the cascade rather than
        # the missing wait.
        shortfall: dict[str, int] = {}

        async def all_leaves_wired() -> bool:
            # One query for every leaf's uplinks rather than one per leaf: the pod carries up to 6
            # leaves, and device__ids already takes the whole set.
            uplinks = await client.filters(
                kind=NetworkInterface,
                branch=CHAIN_BRANCH,
                device__ids=[leaf.id for leaf in leaves],
                role__value="spine",
                include=["ip_address"],
            )
            # Counter, not a pre-seeded dict: `uplinks` was queried with every leaf id, so a
            # membership guard could never be false, and Counter returns 0 for a leaf with none.
            addressed_per_leaf = Counter(interface.device.id for interface in uplinks if interface.ip_address.id)
            shortfall.clear()
            shortfall.update(
                {
                    leaf.hostname.value: addressed_per_leaf[leaf.id]
                    for leaf in leaves
                    if addressed_per_leaf[leaf.id] != expected_uplinks
                }
            )
            return not shortfall

        await wait_until(
            all_leaves_wired,
            what=lambda: (
                f"every leaf in pod {pod.name.value} to carry {expected_uplinks} addressed "
                f"spine-facing interfaces; still short: "
                + ", ".join(f"{host}={count}" for host, count in sorted(shortfall.items()))
            ),
            timeout_seconds=RACK_TIER_TIMEOUT,
        )

        for leaf in leaves:
            assert leaf.loopback_ip.id, f"leaf {leaf.hostname.value} has no loopback IP"

    # Everything from here on mutates FABRIC-A's topology, so it must stay below the tier and wiring
    # assertions: an earlier `amount_of_spines` bump leaves the leaves cabled against the old spine
    # count until the rack generators catch up, which turned test_cascade_leaves_are_fully_wired into
    # a race when this test ran before it.
    #
    # "Below the assertions" is the precise rule, not "below everything that writes". Two tests above
    # this line do write: test_rerunning_upstream_does_not_restamp re-runs the fabric generator, and
    # test_default_branch_does_not_cascade builds super-spines plus IPAM prefixes and pools on the
    # default branch -- and because NetworkPod.checksum is branch-agnostic, its stamp is the value
    # CHAIN_BRANCH subsequently reads. Neither disturbs an assertion below them today (traced), but
    # do not read the ordering rule as a guarantee that nothing above here writes.
    #
    # Stronger than a race, in fact, and it is why the ordering is not merely a convenience: the
    # bump below takes Pod-A2 from 4 to 5 spines, but the Cisco compute leaf template only carries
    # FOUR role="spine" ports (`Ethernet1/[49-52]`, objects/06_device_template.yml) and
    # `build_rack_cabling_plan` silently truncates with `src_interfaces[:dst_device_count]`
    # (src/infrahub_solution_ai_dc/cabling.py). So the fifth spine ends up with no leaf links at all
    # and `addressed == amount_of_spines` -- the invariant test_cascade_leaves_are_fully_wired
    # asserts -- is permanently false afterwards, with no error raised anywhere. Nothing below may
    # re-assert full wiring on Pod-A2, and this test deliberately checks only the spine count.
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
        pods = await get_generated_pods(client, branch=CHAIN_BRANCH)
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
        """Raising amount_of_leafs on a rack should build the extra leaf.

        The rack has to be chosen carefully or the xfail can never flip green when the rule lands,
        which would defeat the whole point of asserting the wanted behaviour:

        * Scoped to Fabric-A's generated pods. An unscoped ``LocationRack`` query returns all 32
          seeded racks -- ``LocationRack`` is ``branch: agnostic``, and Fabric-B/C/D never cascade
          here -- and ``generate_rack.py`` refuses a rack whose pod is not fully generated
          (``pod_amount_of_spines != len(spine_switches)`` raises, and ``require_pod_pool`` raises on
          the unallocated pools), so a foreign rack would keep timing out even with the rule in place.
        * Needs headroom under ``MAX_LEAFS_PER_RACK``. ``amount_of_leafs`` is capped at 2 by the
          schema, so a rack already at 2 rejects the ``+1`` save on validation and never reaches the
          trigger at all.
        """
        pods = await get_generated_pods(client, branch=CHAIN_BRANCH)
        assert pods

        racks = await client.filters(kind=LocationRack, branch=CHAIN_BRANCH, pod__ids=[pod.id for pod in pods])
        rack = next((item for item in racks if item.amount_of_leafs.value < MAX_LEAFS_PER_RACK), None)
        assert rack is not None, (
            f"no {FABRIC_NAME} rack has leaf-count headroom under {MAX_LEAFS_PER_RACK}; "
            "this test cannot raise amount_of_leafs without tripping schema validation"
        )

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
