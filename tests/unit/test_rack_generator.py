"""Tests for the RackGenerator prerequisite guards."""

from __future__ import annotations

import asyncio

import pytest

from generators.generate_rack import RackGenerator


def _rack_query_data(*, loopback_pool: bool, prefix_pool: bool) -> dict:
    """Build a RackGeneratorQuery payload, optionally omitting the pod IP pools."""
    return {
        "LocationRack": {
            "edges": [
                {
                    "node": {
                        "id": "rack-1",
                        "name": {"value": "Rack-A2-1"},
                        "checksum": {"value": "deadbeef"},
                        "index": {"value": 1},
                        "rack_type": {"value": "standard"},
                        "amount_of_leafs": {"value": 2},
                        "leaf_switch_template": {"node": {"__typename": "CoreObjectTemplate", "id": "tmpl-1"}},
                        "parent": {"node": None},
                        "pod": {
                            "node": {
                                "id": "pod-1",
                                "name": {"value": "Pod-A2"},
                                "index": {"value": 2},
                                "amount_of_spines": {"value": 4},
                                "leaf_interface_sorting_method": {"value": "sort_a"},
                                "spine_interface_sorting_method": {"value": "sort_b"},
                                "prefix_pool": {"node": {"id": "pfx-1"} if prefix_pool else None},
                                "loopback_pool": {"node": {"id": "lo-1"} if loopback_pool else None},
                            }
                        },
                    }
                }
            ]
        }
    }


class TestRackGeneratorPoolGuard:
    """A rack cannot be generated before its pod has IP pools (i.e. before generate-pod runs)."""

    def test_missing_loopback_pool_raises_clear_error(self) -> None:
        generator = RackGenerator.__new__(RackGenerator)
        data = _rack_query_data(loopback_pool=False, prefix_pool=True)
        with pytest.raises(RuntimeError, match="run the pod generator"):
            asyncio.run(generator.generate(data))

    def test_missing_prefix_pool_raises_clear_error(self) -> None:
        generator = RackGenerator.__new__(RackGenerator)
        data = _rack_query_data(loopback_pool=True, prefix_pool=False)
        with pytest.raises(RuntimeError, match="run the pod generator"):
            asyncio.run(generator.generate(data))

    def test_error_names_the_pod(self) -> None:
        generator = RackGenerator.__new__(RackGenerator)
        data = _rack_query_data(loopback_pool=False, prefix_pool=False)
        with pytest.raises(RuntimeError, match="pod-a2"):
            asyncio.run(generator.generate(data))
