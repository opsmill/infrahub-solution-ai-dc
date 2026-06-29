"""US3 rack-placement tests for overlay segment resolution (T036, SC-005).

These tests exercise `resolve_segment_devices` rack-scoped filtering: a segment
may be pinned to a subset of racks instead of the advertise-all default. They
map to US3 rack-placement acceptance (SC-005) — narrowing a segment to specific
racks must return exactly those racks' leafs and nothing else.
"""

from infrahub_solution_ai_dc.overlay import resolve_segment_devices


class TestRackPlacement:
    """US3 rack-placement (SC-005): rack-scoped segment device resolution."""

    def test_single_rack_returns_only_that_racks_leafs(self) -> None:
        """Scoping to one rack returns only that rack's leafs, not other racks'."""
        leaf_a1 = object()
        leaf_a2 = object()
        leaf_b1 = object()
        leaf_c1 = object()
        leaf_c2 = object()
        leafs_by_rack: dict[str, list[object]] = {
            "rack-a": [leaf_a1, leaf_a2],
            "rack-b": [leaf_b1],
            "rack-c": [leaf_c1, leaf_c2],
        }

        result = resolve_segment_devices(["rack-b"], leafs_by_rack)

        assert result == [leaf_b1]

    def test_subset_of_racks_in_rack_ids_order(self) -> None:
        """Scoping to 2 of 3 racks returns exactly those racks' leafs, in rack_ids order."""
        leaf_a1 = object()
        leaf_a2 = object()
        leaf_b1 = object()
        leaf_c1 = object()
        leaf_c2 = object()
        leafs_by_rack: dict[str, list[object]] = {
            "rack-a": [leaf_a1, leaf_a2],
            "rack-b": [leaf_b1],
            "rack-c": [leaf_c1, leaf_c2],
        }

        result = resolve_segment_devices(["rack-c", "rack-a"], leafs_by_rack)

        assert result == [leaf_c1, leaf_c2, leaf_a1, leaf_a2]

    def test_unknown_rack_id_contributes_no_leafs(self) -> None:
        """An unknown rack id in rack_ids is silently skipped (no error, no leafs)."""
        leaf_a1 = object()
        leaf_b1 = object()
        leafs_by_rack: dict[str, list[object]] = {
            "rack-a": [leaf_a1],
            "rack-b": [leaf_b1],
        }

        result = resolve_segment_devices(["rack-a", "rack-nope"], leafs_by_rack)

        assert result == [leaf_a1]

    def test_empty_rack_ids_advertises_all_leafs(self) -> None:
        """Empty rack_ids returns ALL leafs across all racks — the advertise-all contrast case."""
        leaf_a1 = object()
        leaf_a2 = object()
        leaf_b1 = object()
        leaf_c1 = object()
        leaf_c2 = object()
        leafs_by_rack: dict[str, list[object]] = {
            "rack-a": [leaf_a1, leaf_a2],
            "rack-b": [leaf_b1],
            "rack-c": [leaf_c1, leaf_c2],
        }

        result = resolve_segment_devices([], leafs_by_rack)

        assert result == [leaf_a1, leaf_a2, leaf_b1, leaf_c1, leaf_c2]

    def test_repeated_rack_id_does_not_duplicate_leafs(self) -> None:
        """A rack id listed twice yields each leaf once (identity dedup), first-seen order kept."""
        leaf_a1 = object()
        leaf_a2 = object()
        leaf_b1 = object()
        leafs_by_rack: dict[str, list[object]] = {
            "rack-a": [leaf_a1, leaf_a2],
            "rack-b": [leaf_b1],
        }

        result = resolve_segment_devices(["rack-a", "rack-b", "rack-a"], leafs_by_rack)

        assert result == [leaf_a1, leaf_a2, leaf_b1]
