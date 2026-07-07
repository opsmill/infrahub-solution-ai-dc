"""Tests for EVPN/VXLAN overlay helpers (US1 unit tests)."""

from infrahub_solution_ai_dc.overlay import (
    resolve_segment_devices,
    route_target,
    rr_client,
)


class TestRouteTarget:
    def test_standard_asn(self) -> None:
        """A 16-bit ASN and VNI are joined with a colon."""
        assert route_target(65000, 10001) == "65000:10001"

    def test_another_pair(self) -> None:
        """Different asn/vni values format correctly."""
        assert route_target(65001, 20002) == "65001:20002"

    def test_private_32bit_asn(self) -> None:
        """A private 32-bit ASN is rendered without truncation."""
        assert route_target(4200000000, 50001) == "4200000000:50001"


class TestResolveSegmentDevices:
    def test_advertise_all_flattens_every_leaf(self) -> None:
        """Empty rack_ids returns every leaf across all racks in insertion order."""
        leaf_a1 = object()
        leaf_a2 = object()
        leaf_b1 = object()
        leafs_by_rack = {
            "rack-a": [leaf_a1, leaf_a2],
            "rack-b": [leaf_b1],
        }

        result = resolve_segment_devices([], leafs_by_rack)

        assert result == [leaf_a1, leaf_a2, leaf_b1]

    def test_advertise_all_empty_mapping(self) -> None:
        """Empty rack_ids with an empty mapping returns an empty list."""
        result: list[str] = resolve_segment_devices([], {})
        assert result == []

    def test_selected_racks_only(self) -> None:
        """Non-empty rack_ids returns only the leafs of the listed racks in order."""
        leaf_a1 = "leaf-a1"
        leaf_b1 = "leaf-b1"
        leaf_c1 = "leaf-c1"
        leafs_by_rack = {
            "rack-a": [leaf_a1],
            "rack-b": [leaf_b1],
            "rack-c": [leaf_c1],
        }

        result = resolve_segment_devices(["rack-c", "rack-a"], leafs_by_rack)

        assert result == [leaf_c1, leaf_a1]

    def test_unknown_rack_id_is_ignored(self) -> None:
        """A rack id with no entry in the mapping contributes no leafs."""
        leaf_a1 = object()
        leafs_by_rack = {"rack-a": [leaf_a1]}

        result = resolve_segment_devices(["rack-a", "rack-missing"], leafs_by_rack)

        assert result == [leaf_a1]

    def test_dedupes_by_identity_preserving_first_seen(self) -> None:
        """A leaf reachable via repeated rack ids appears once, first-seen order kept."""
        leaf_a1 = object()
        leaf_b1 = object()
        leafs_by_rack = {
            "rack-a": [leaf_a1],
            "rack-b": [leaf_b1],
        }

        result = resolve_segment_devices(["rack-a", "rack-b", "rack-a"], leafs_by_rack)

        assert result == [leaf_a1, leaf_b1]


class TestRrClient:
    def test_spine_reflects_for_leaf(self) -> None:
        """A spine outranks a leaf, so the leaf is its RR client."""
        assert rr_client("spine", "leaf") is True

    def test_super_spine_reflects_for_spine(self) -> None:
        """A super-spine outranks a spine, so the spine is its RR client."""
        assert rr_client("super_spine", "spine") is True

    def test_leaf_is_client_not_reflector(self) -> None:
        """A leaf never reflects toward its spines."""
        assert rr_client("leaf", "spine") is False

    def test_spine_is_client_of_super_spine(self) -> None:
        """A spine is a client toward the super-spines, not their reflector."""
        assert rr_client("spine", "super_spine") is False

    def test_same_tier_is_not_client(self) -> None:
        """Peers of the same tier never treat each other as RR clients."""
        assert rr_client("spine", "spine") is False

    def test_unknown_role_is_never_reflector(self) -> None:
        """An unknown local role ranks below every known tier."""
        assert rr_client("borderleaf", "leaf") is False
