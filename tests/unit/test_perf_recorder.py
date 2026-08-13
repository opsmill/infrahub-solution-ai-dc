"""Unit coverage for the version-comparison timing recorder.

The outcome mapping is the part worth pinning. It is easy to get wrong in a way that is invisible
until a comparison report is read: a ``@pytest.mark.skip`` test never produces a ``call`` phase, and a
naive "record the call phase outcome" recorder silently labels those "unknown" -- which then shows up
in the report as an ambiguous state rather than as the skip it is. That exact bug shipped once and is
what these tests exist to prevent recurring.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import pytest

from tests.perf import PerfRecorder

if TYPE_CHECKING:
    from pathlib import Path


@dataclass
class FakeReport:
    """The subset of ``pytest.TestReport`` that ``record_report`` touches.

    ``wasxfail`` is absent by default and set as an attribute only for the xfail cases, mirroring
    pytest: the recorder distinguishes xfail from skip with ``hasattr``, so a fake that always carries
    the attribute would not exercise the branch.
    """

    nodeid: str
    when: str
    outcome: str
    duration: float = 0.0
    longrepr: str | None = None


def make_recorder(tmp_path: Path) -> PerfRecorder:
    return PerfRecorder(output_path=tmp_path / "out.json", infrahub_version="test")


def record(recorder: PerfRecorder, *reports: Any) -> None:  # noqa: ANN401 - fakes, not TestReport
    for report in reports:
        recorder.record_report(report)


def outcome_of(recorder: PerfRecorder, nodeid: str) -> str:
    return recorder.records[nodeid].outcome


class TestOutcomeMapping:
    def test_passing_test_is_passed(self, tmp_path: Path) -> None:
        recorder = make_recorder(tmp_path)
        record(
            recorder,
            FakeReport(nodeid="t::a", when="setup", outcome="passed"),
            FakeReport(nodeid="t::a", when="call", outcome="passed"),
            FakeReport(nodeid="t::a", when="teardown", outcome="passed"),
        )
        assert outcome_of(recorder, "t::a") == "passed"

    def test_marker_skip_is_skipped_not_unknown(self, tmp_path: Path) -> None:
        """A `@pytest.mark.skip` test reports skipped at setup and has no call phase at all."""
        recorder = make_recorder(tmp_path)
        record(
            recorder,
            FakeReport(nodeid="t::b", when="setup", outcome="skipped"),
            FakeReport(nodeid="t::b", when="teardown", outcome="passed"),
        )
        assert outcome_of(recorder, "t::b") == "skipped"

    def test_runtime_skip_is_skipped(self, tmp_path: Path) -> None:
        """`pytest.skip()` inside the body reports skipped at the call phase instead."""
        recorder = make_recorder(tmp_path)
        record(
            recorder,
            FakeReport(nodeid="t::c", when="setup", outcome="passed"),
            FakeReport(nodeid="t::c", when="call", outcome="skipped"),
        )
        assert outcome_of(recorder, "t::c") == "skipped"

    def test_xfail_is_distinct_from_skip(self, tmp_path: Path) -> None:
        """xfail also reports outcome "skipped"; only ``wasxfail`` separates the two."""
        recorder = make_recorder(tmp_path)
        report = FakeReport(nodeid="t::d", when="call", outcome="skipped")
        report.wasxfail = "known gap"  # type: ignore[attr-defined]
        record(recorder, report)
        assert outcome_of(recorder, "t::d") == "xfailed"

    def test_xpass_is_distinct_from_pass(self, tmp_path: Path) -> None:
        """A strict-xfail that starts passing must be visible -- it means the gap closed."""
        recorder = make_recorder(tmp_path)
        report = FakeReport(nodeid="t::e", when="call", outcome="passed")
        report.wasxfail = "fixed now"  # type: ignore[attr-defined]
        record(recorder, report)
        assert outcome_of(recorder, "t::e") == "xpassed"

    def test_call_failure_is_failed_and_keeps_detail(self, tmp_path: Path) -> None:
        recorder = make_recorder(tmp_path)
        record(
            recorder,
            FakeReport(nodeid="t::f", when="setup", outcome="passed"),
            FakeReport(nodeid="t::f", when="call", outcome="failed", longrepr="assert 1 == 2"),
        )
        assert outcome_of(recorder, "t::f") == "failed"
        assert recorder.records["t::f"].longrepr == "assert 1 == 2"

    def test_setup_failure_is_error(self, tmp_path: Path) -> None:
        """A fixture blowing up produces no call phase; it must not read as a missing test."""
        recorder = make_recorder(tmp_path)
        record(recorder, FakeReport(nodeid="t::g", when="setup", outcome="failed", longrepr="fixture boom"))
        assert outcome_of(recorder, "t::g") == "error"
        assert recorder.records["t::g"].longrepr == "fixture boom"


class TestPayload:
    def test_durations_are_summed_per_phase(self, tmp_path: Path) -> None:
        recorder = make_recorder(tmp_path)
        record(
            recorder,
            FakeReport(nodeid="t::h", when="setup", outcome="passed", duration=120.0),
            FakeReport(nodeid="t::h", when="call", outcome="passed", duration=30.5),
            FakeReport(nodeid="t::h", when="teardown", outcome="passed", duration=1.25),
        )
        entry = recorder.payload()["tests"][0]
        assert entry["total_seconds"] == pytest.approx(151.75)
        # Kept per phase, not just summed: container startup lands in the setup of a class's first
        # test, and conflating it with the test body would misattribute stack boot time.
        assert entry["durations"] == {"setup": 120.0, "call": 30.5, "teardown": 1.25}

    def test_write_produces_readable_json_with_context(self, tmp_path: Path) -> None:
        recorder = make_recorder(tmp_path)
        record(recorder, FakeReport(nodeid="t::i", when="call", outcome="passed", duration=1.0))
        recorder.add_context("image", "opsmill/infrahub-solution-ai-dc:1.11.0b1")
        recorder.write()

        payload = json.loads((tmp_path / "out.json").read_text(encoding="utf-8"))
        assert payload["infrahub_version"] == "test"
        assert payload["context"]["image"] == "opsmill/infrahub-solution-ai-dc:1.11.0b1"
        assert [test["nodeid"] for test in payload["tests"]] == ["t::i"]

    def test_tests_are_sorted_by_nodeid(self, tmp_path: Path) -> None:
        """Stable ordering, so two result files diff cleanly outside the comparison script too."""
        recorder = make_recorder(tmp_path)
        record(
            recorder,
            FakeReport(nodeid="t::z", when="call", outcome="passed"),
            FakeReport(nodeid="t::a", when="call", outcome="passed"),
        )
        assert [test["nodeid"] for test in recorder.payload()["tests"]] == ["t::a", "t::z"]
