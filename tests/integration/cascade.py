"""Shared machinery for driving the fabric -> pod -> rack generator cascade in integration tests.

Extracted from ``test_generator_chain.py`` (which proved it against a live stack) so that the overlay
and server-service suites can build real leaf devices instead of being skipped. Three facts make the
cascade impossible to fire by accident, and every one of them is encoded here:

1. ``triggers.yml`` is loaded by neither ``inv load`` nor repository sync -- it is a manual step
   (AGENTS.md). Without ``load_trigger_rules`` there are no rules at all and the cascade stops dead
   after the fabric tier, with no error anywhere.
2. Every rule sets ``branch_scope: other_branches``, which compiles to an event match of
   ``infrahub.branch.name != <default_branch>``. The cascade therefore cannot fire on ``main``; every
   caller must work on a dedicated branch.
3. The chain has no automatic entry point -- creating or resizing a fabric dispatches nothing (all
   four dispatch paths are closed in this repo). The fabric generator must be invoked explicitly.

Waits are condition-based with env-overridable ceilings; nothing here sleeps a fixed interval hoping
convergence happened.
"""

from __future__ import annotations

import asyncio
import os
import time
from typing import TYPE_CHECKING

import pytest
from infrahub_sdk.protocols import CoreGeneratorAction, CoreGeneratorDefinition, CoreNodeTriggerRule
from infrahub_sdk.spec.object import ObjectFile

from infrahub_solution_ai_dc.protocols import LocationRack, NetworkDevice, NetworkFabric, NetworkPod

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from pathlib import Path

    from infrahub_sdk import InfrahubClient

# Fabric-A from objects/10_fabric.yml: 6 super-spines, one role="fabric" pod holding them (Pod-A1)
# plus two generated pods (Pod-A2, Pod-A3), each with its own racks.
FABRIC_NAME = "Fabric-A"
FABRIC_POD_ROLE = "fabric"


def env_seconds(name: str, default: float) -> float:
    """Read a seconds-valued env override, falling back on anything unparseable.

    Read at import time by the module-level ceilings below, so a bare ``float()`` on a typo'd or empty
    override would raise during collection and take a whole module (not just one test) down with a
    collection error.
    """
    try:
        return float(os.environ[name])
    except (KeyError, ValueError):
        return default


# Ceilings, not expected durations: each wait returns as soon as its condition holds.
FABRIC_TIER_TIMEOUT = env_seconds("AI_DC_FABRIC_TIER_TIMEOUT", 600)
POD_TIER_TIMEOUT = env_seconds("AI_DC_POD_TIER_TIMEOUT", 900)
RACK_TIER_TIMEOUT = env_seconds("AI_DC_RACK_TIER_TIMEOUT", 1200)
# How long to watch for something that must NOT happen. Bounded on purpose: a negative assertion can
# only ever be "nothing within this window".
NO_CASCADE_WINDOW = env_seconds("AI_DC_NO_CASCADE_WINDOW", 120)
# Ceiling for a generator run that is expected to converge quickly (a single object materializing),
# as opposed to a whole tier.
GENERATOR_TIMEOUT = env_seconds("AI_DC_GENERATOR_TIMEOUT", 600)
POLL_INTERVAL = 5.0
# ``wait_until`` polls at this rate for its first ``FAST_POLL_WINDOW`` seconds before settling to
# ``POLL_INTERVAL``, so a condition that is already true is noticed promptly instead of up to 5s
# later. ``stays_false`` deliberately does not use it -- it wants the whole window regardless.
FAST_POLL_INTERVAL = 1.0
FAST_POLL_WINDOW = 15.0

# wait_until_completion is false so a long generator run cannot trip the client HTTP timeout; callers
# poll the resulting data instead. Registered as CoreGeneratorDefinitionRun.
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


async def load_trigger_rules(client: InfrahubClient, root_directory: Path) -> None:
    """Load triggers.yml -- the step neither ``inv load`` nor repository sync performs.

    Must run *after* repository sync: each CoreGeneratorAction references a generator definition by
    name, which only exists once the repo has been imported.
    """
    trigger_files = ObjectFile.load_from_disk(paths=[root_directory / "triggers.yml"])
    assert trigger_files, "triggers.yml produced no object documents"

    for trigger_file in trigger_files:
        trigger_file.validate_content()
        await trigger_file.process(client=client)

    actions = await client.all(kind=CoreGeneratorAction)
    assert {action.name.value for action in actions} >= {
        "run-fabric-generator",
        "run-pod-generator",
        "run-rack-generator",
    }, "a generator action is missing; the cascade cannot dispatch"

    # NetworkFabric is included deliberately: a rule for it exists only so that resizing a fabric
    # regenerates. Asserting it here means a triggers.yml that loses the rule fails at load time with
    # a clear message, rather than 300s later inside test_fabric_super_spine_count_change_regenerates.
    rules = await client.all(kind=CoreNodeTriggerRule)
    assert {"NetworkFabric", "NetworkPod", "LocationRack"} <= {rule.node_kind.value for rule in rules}, (
        "a tier has no trigger rule; fabric -> pod -> rack cannot fire end to end"
    )


async def count_devices_in_pod(client: InfrahubClient, *, branch: str, pod_id: str, role: str) -> int:
    """Count the devices of a given role attached to a pod.

    ``count`` rather than ``filters`` + ``len``: these helpers are the body of nearly every poll, so
    hundreds of calls per run would otherwise hydrate complete device nodes -- every attribute and
    every relationship peer -- purely to discard them and take a length.
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
    """Fetch the fabric under test and return only the pods its PodGenerator manages."""
    fabric = await client.get(kind=NetworkFabric, name__value=FABRIC_NAME, branch=branch)
    return generated_pods(await get_fabric_pods(client, branch=branch, fabric_id=fabric.id))


async def provision_fabric_cascade(client: InfrahubClient, *, branch: str) -> None:
    """Drive fabric -> pod -> rack to completion on ``branch``, leaving real leaf devices behind.

    This is the setup that the overlay and server-service suites need and that neither ``inv load``
    nor repository sync provides. It asserts convergence at each tier rather than at the end only, so
    a truncated cascade is reported against the tier that actually stalled instead of surfacing as a
    confusing "no leaf devices" much later.

    Caller contract: ``branch`` must not be the default branch (every rule is
    ``branch_scope: other_branches``) and ``load_trigger_rules`` must already have run.
    """
    fabric = await client.get(kind=NetworkFabric, name__value=FABRIC_NAME, branch=branch)
    expected_super_spines = fabric.amount_of_super_spines.value
    fabric_pod = await client.get(kind=NetworkPod, branch=branch, parent__ids=[fabric.id], role__value=FABRIC_POD_ROLE)

    # Tier 1 is the only explicit invocation; everything below arrives by trigger.
    await run_generator(client, definition_name="generate-fabric", branch=branch, node_ids=[fabric.id])

    async def super_spines_ready() -> bool:
        count = await count_devices_in_pod(client, branch=branch, pod_id=fabric_pod.id, role="super_spine")
        return count >= expected_super_spines

    await wait_until(
        super_spines_ready,
        what=f"{expected_super_spines} super-spine devices in {FABRIC_NAME}",
        timeout_seconds=FABRIC_TIER_TIMEOUT,
    )

    # Tier 2, by trigger only: the fabric generator's pod-checksum stamp dispatches the pod generator.
    pods = generated_pods(await get_fabric_pods(client, branch=branch, fabric_id=fabric.id))
    assert pods, f"{FABRIC_NAME} has no non-fabric pods to cascade into"

    async def all_pods_have_spines() -> bool:
        for pod in pods:
            if (
                await count_devices_in_pod(client, branch=branch, pod_id=pod.id, role="spine")
                < pod.amount_of_spines.value
            ):
                return False
        return True

    await wait_until(
        all_pods_have_spines,
        what="spines in every pod of " + FABRIC_NAME + " (fabric -> pod trigger)",
        timeout_seconds=POD_TIER_TIMEOUT,
    )

    # Tier 3, by trigger only: each pod generator stamps its racks' checksums.
    racks = await client.filters(kind=LocationRack, branch=branch, pod__ids=[pod.id for pod in pods])
    assert racks, f"{FABRIC_NAME} pods have no racks to cascade into"

    async def all_racks_have_leaves() -> bool:
        for rack in racks:
            if await count_leaves_in_rack(client, branch=branch, rack_id=rack.id) < rack.amount_of_leafs.value:
                return False
        return True

    await wait_until(
        all_racks_have_leaves,
        what="leaf devices in every rack of " + FABRIC_NAME + " (pod -> rack trigger)",
        timeout_seconds=RACK_TIER_TIMEOUT,
    )
