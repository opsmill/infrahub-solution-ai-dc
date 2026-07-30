"""Tests for ``RackGenerator``'s pod-pool guard (generators/generate_rack.py).

A rack's leaf switches take their loopback address from the pod's loopback pool, and their
leaf<->spine /31s from the pod's prefix pool. Both pools are allocated by the **PodGenerator**, so a
rack whose pod has not finished generating reaches the RackGenerator with those relationships unset.

Before the guard, ``generate`` dereferenced them straight through
(``rack.pod.node.loopback_pool.node.id``) and the run died with
``AttributeError: 'NoneType' object has no attribute 'id'`` — which names neither the rack, nor the
pod, nor which pool was missing. Observed in the wild on Pod-B2/Pod-B3/Pod-C2, whose pods had no
pools because the fabric/pod cascade above them had not run.

These tests pin the *diagnosability* of that failure, not just that it fails: the message has to name
the rack, the pod and the pool, because that is what tells an operator which cascade to wait for.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from generators.generate_rack import require_pod_pool


@dataclass
class _PoolNode:
    """Stand-in for a pool node — ``id`` is ``None`` when the pool exists but was never allocated."""

    id: str | None


@dataclass
class _PoolRelationship:
    """A to-one pool relationship exposing ``.node`` (the generator query's shape)."""

    node: _PoolNode | None


class TestRequirePodPool:
    """The happy path: a fully generated pod yields its pool id unchanged."""

    def test_an_allocated_pool_yields_its_id(self) -> None:
        pool = _PoolRelationship(node=_PoolNode(id="pool-abc"))

        got = require_pod_pool(pool, pool_name="loopback_pool", rack="Rack-A2-1", pod="Pod-A2")

        assert got == "pool-abc"


class TestRequirePodPoolFailsLoud:
    """Every "not ready" shape must raise, and must raise something an operator can act on."""

    @pytest.mark.parametrize(
        "pool",
        [
            pytest.param(None, id="relationship-absent"),
            pytest.param(_PoolRelationship(node=None), id="node-unset"),
            pytest.param(_PoolRelationship(node=_PoolNode(id=None)), id="node-without-id"),
        ],
    )
    def test_an_unready_pool_raises_runtime_error(self, pool: _PoolRelationship | None) -> None:
        """``node-unset`` is the shape seen in production; the other two are the same failure earlier."""
        with pytest.raises(RuntimeError):
            require_pod_pool(pool, pool_name="loopback_pool", rack="Rack-B2-1", pod="Pod-B2")

    def test_the_message_names_the_rack_the_pod_and_the_pool(self) -> None:
        """The whole point of the guard: an AttributeError named none of these three."""
        with pytest.raises(RuntimeError) as excinfo:
            require_pod_pool(
                _PoolRelationship(node=None), pool_name="prefix_pool", rack="Rack-B2-1", pod="Pod-B2"
            )

        message = str(excinfo.value)
        assert "Rack-B2-1" in message
        assert "Pod-B2" in message
        assert "prefix_pool" in message

    def test_the_message_points_at_the_pod_generator_as_the_remedy(self) -> None:
        """Naming what is missing is only half of it — the operator needs to know what fills it in."""
        with pytest.raises(RuntimeError, match="PodGenerator"):
            require_pod_pool(_PoolRelationship(node=None), pool_name="loopback_pool", rack="R", pod="P")

    def test_it_does_not_raise_attribute_error(self) -> None:
        """Guards against a regression to the original bug, where the failure was an AttributeError."""
        with pytest.raises(RuntimeError):
            require_pod_pool(None, pool_name="loopback_pool", rack="R", pod="P")
