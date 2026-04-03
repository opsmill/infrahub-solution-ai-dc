"""Tests for the GeneratorMixin checksum calculation."""

from unittest.mock import MagicMock

from infrahub_solution_ai_dc.generator import GeneratorMixin


class TestCalculateChecksum:
    def _create_mixin(
        self, related_group_ids: list[str], related_node_ids: list[str]
    ) -> GeneratorMixin:
        mixin = GeneratorMixin()
        mixin.client = MagicMock()
        mixin.client.group_context.related_group_ids = related_group_ids
        mixin.client.group_context.related_node_ids = related_node_ids
        return mixin

    def test_deterministic_output(self) -> None:
        """Same inputs produce same checksum."""
        mixin1 = self._create_mixin(["g1"], ["n1", "n2"])
        mixin2 = self._create_mixin(["g1"], ["n1", "n2"])
        assert mixin1.calculate_checksum() == mixin2.calculate_checksum()

    def test_order_independent(self) -> None:
        """IDs are sorted before hashing, so order doesn't matter."""
        mixin1 = self._create_mixin(["g2", "g1"], ["n2", "n1"])
        mixin2 = self._create_mixin(["g1", "g2"], ["n1", "n2"])
        assert mixin1.calculate_checksum() == mixin2.calculate_checksum()

    def test_different_ids_produce_different_checksums(self) -> None:
        mixin1 = self._create_mixin(["g1"], ["n1"])
        mixin2 = self._create_mixin(["g1"], ["n2"])
        assert mixin1.calculate_checksum() != mixin2.calculate_checksum()

    def test_empty_ids(self) -> None:
        """Empty ID lists still produce a valid hex digest."""
        mixin = self._create_mixin([], [])
        result = mixin.calculate_checksum()
        assert isinstance(result, str)
        assert len(result) == 64  # SHA-256 hex digest length

    def test_returns_sha256_hex(self) -> None:
        mixin = self._create_mixin(["a"], ["b"])
        result = mixin.calculate_checksum()
        assert len(result) == 64
        int(result, 16)  # Validates it's valid hex
