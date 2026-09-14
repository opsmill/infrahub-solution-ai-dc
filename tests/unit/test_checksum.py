"""Tests for the generator checksum: how it is derived, and when it is stamped."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast
from unittest.mock import MagicMock

import pytest

from infrahub_solution_ai_dc.checksum import Checksum

if TYPE_CHECKING:
    from infrahub_solution_ai_dc.protocols import GeneratorTarget

SHA256_HEX_LENGTH = 64


@dataclass
class _Attribute:
    value: str | None


class _TargetStub:
    """A ``GeneratorTarget`` recording how it was saved."""

    def __init__(self, checksum: str | None = None, label: str = "pod-a1", node_id: str = "id-1") -> None:
        self.checksum = _Attribute(checksum)
        self.display_label = label
        self.id = node_id
        self.saves: list[dict[str, Any]] = []

    async def save(self, *, allow_upsert: bool, update_group_context: bool | None) -> None:
        self.saves.append({"allow_upsert": allow_upsert, "update_group_context": update_group_context})


def _as_targets(*stubs: _TargetStub) -> list[GeneratorTarget]:
    return [cast("GeneratorTarget", stub) for stub in stubs]


def _session(group_ids: list[str], node_ids: list[str]) -> Any:  # noqa: ANN401
    client = MagicMock()
    client.group_context.related_group_ids = group_ids
    client.group_context.related_node_ids = node_ids
    return client


class TestDigest:
    def test_deterministic_output(self) -> None:
        assert Checksum.over_contents(["n1", "n2"]) == Checksum.over_contents(["n1", "n2"])

    def test_order_independent(self) -> None:
        """Only membership of the id set moves the digest, never the order it arrived in."""
        assert Checksum.over_contents(["n2", "n1"]) == Checksum.over_contents(["n1", "n2"])

    def test_different_ids_produce_different_digests(self) -> None:
        assert Checksum.over_contents(["n1"]) != Checksum.over_contents(["n2"])

    def test_empty_ids_still_digest(self) -> None:
        assert len(Checksum.over_contents([]).digest) == SHA256_HEX_LENGTH

    def test_digest_is_sha256_hex(self) -> None:
        digest = Checksum.over_contents(["a", "b"]).digest
        assert len(digest) == SHA256_HEX_LENGTH
        int(digest, 16)

    def test_over_session_reads_both_id_kinds(self) -> None:
        """Group ids and node ids both feed the session digest."""
        assert Checksum.over_session(_session(["g1"], ["n1"])) != Checksum.over_session(_session([], ["n1"]))

    def test_the_two_sources_share_one_digest_function(self) -> None:
        """A session and a content digest over the same ids agree — one hash, two id sources."""
        assert Checksum.over_session(_session(["g1"], ["n1"])) == Checksum.over_contents(["g1", "n1"])


class TestStamping:
    async def test_stamps_a_target_whose_checksum_differs(self) -> None:
        target = _TargetStub(checksum="stale")
        checksum = Checksum.over_contents(["n1"])

        changed = await checksum.stamp_on(_as_targets(target), logger=logging.getLogger("test"), track=False)

        assert changed == 1
        assert target.checksum.value == checksum.digest
        assert len(target.saves) == 1

    async def test_an_unchanged_target_is_never_saved(self) -> None:
        """The no-self-retrigger rule: re-stamping an identical digest would re-fire the trigger."""
        checksum = Checksum.over_contents(["n1"])
        target = _TargetStub(checksum=checksum.digest)

        changed = await checksum.stamp_on(_as_targets(target), logger=logging.getLogger("test"), track=False)

        assert changed == 0
        assert target.saves == []

    async def test_only_the_stale_targets_of_a_batch_are_written(self) -> None:
        checksum = Checksum.over_contents(["n1"])
        fresh = _TargetStub(checksum=checksum.digest, label="rack-1")
        stale = _TargetStub(checksum="stale", label="rack-2")

        changed = await checksum.stamp_on(_as_targets(fresh, stale), logger=logging.getLogger("test"), track=True)

        assert changed == 1
        assert fresh.saves == []
        assert len(stale.saves) == 1

    @pytest.mark.parametrize("track", [True, False, None])
    async def test_track_reaches_update_group_context(self, track: bool | None) -> None:
        """Whether the stamped node joins the generator's group is the caller's decision."""
        target = _TargetStub(checksum="stale")

        await Checksum.over_contents(["n1"]).stamp_on(
            _as_targets(target), logger=logging.getLogger("test"), track=track
        )

        assert target.saves[0]["update_group_context"] is track

    async def test_a_first_stamp_lands_on_an_unstamped_target(self) -> None:
        target = _TargetStub(checksum=None)

        changed = await Checksum.over_contents(["n1"]).stamp_on(
            _as_targets(target), logger=logging.getLogger("test"), track=False
        )

        assert changed == 1

    async def test_each_write_is_logged_and_a_settled_run_is_silent(self, caplog: pytest.LogCaptureFixture) -> None:
        checksum = Checksum.over_contents(["n1"])
        stale = _TargetStub(checksum="stale", label="pod-a2")
        fresh = _TargetStub(checksum=checksum.digest, label="pod-a3")
        logger = logging.getLogger("test.checksum")

        with caplog.at_level(logging.INFO, logger="test.checksum"):
            await checksum.stamp_on(_as_targets(stale, fresh), logger=logger, track=True)

        assert len(caplog.records) == 1
        assert "pod-a2" in caplog.records[0].message

    async def test_the_id_labels_a_target_with_no_display_label(self, caplog: pytest.LogCaptureFixture) -> None:
        target = _TargetStub(checksum="stale", label="", node_id="abc-123")
        logger = logging.getLogger("test.checksum")

        with caplog.at_level(logging.INFO, logger="test.checksum"):
            await Checksum.over_contents(["n1"]).stamp_on(_as_targets(target), logger=logger, track=False)

        assert "abc-123" in caplog.records[0].message
