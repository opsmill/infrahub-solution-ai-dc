"""Local-only timing capture, so the same suite run against two Infrahub versions can be compared.

Deliberately does not use ``infrahub_testcontainers``' bundled performance plugin. That plugin's
``--performance-report`` calls ``InfrahubPerformanceTest.finalize`` -> ``send_results``, which POSTs
the payload -- including ``env_vars`` and container metrics -- to ``--performance-result-address``,
whose default is a public webhook.site URL. It also scrapes a ``scraper`` service that the
non-cluster compose does not run. This module writes a JSON file and nothing else.

Off unless ``AI_DC_PERF_OUT`` names an output path, so a normal ``inv test`` / CI run is unchanged.

What the numbers mean: every test in the integration suite is a *phase of one long scenario* sharing
a class-scoped stack, not an independent benchmark. A single test's duration is therefore only
meaningful next to the same test in the other run, and the tier tests measure convergence latency
(how long the platform took to cascade), which is the interesting quantity here. Suite wall-clock
includes container startup and image differences, so it is reported but is the weakest signal.
"""

from __future__ import annotations

import json
import os
import platform
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import pytest

ENV_OUTPUT_PATH = "AI_DC_PERF_OUT"


@dataclass
class TestRecord:
    nodeid: str
    outcome: str = "unknown"
    # Keyed by pytest phase (setup/call/teardown). Stack startup lands in the setup of the first
    # test of a class, which is why the phases are kept apart rather than summed.
    durations: dict[str, float] = field(default_factory=dict)
    longrepr: str | None = None

    @property
    def total(self) -> float:
        return sum(self.durations.values())


@dataclass
class PerfRecorder:
    """Accumulates per-test timings for one pytest session and writes them as JSON."""

    output_path: Path
    infrahub_version: str
    records: dict[str, TestRecord] = field(default_factory=dict)
    context: dict[str, Any] = field(default_factory=dict)
    started_at: float = field(default_factory=time.monotonic)
    started_wall: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def record_report(self, report: pytest.TestReport) -> None:
        record = self.records.setdefault(report.nodeid, TestRecord(nodeid=report.nodeid))
        record.durations[report.when] = report.duration

        # An xfailed test reports outcome "skipped" with a wasxfail attribute; keep them distinct so
        # the comparison can tell "still xfailing" from "newly skipped".
        if hasattr(report, "wasxfail"):
            record.outcome = "xpassed" if report.outcome == "passed" else "xfailed"
        elif report.outcome == "skipped":
            # Checked before the `when == "call"` branch below, not after: a `@pytest.mark.skip` test
            # is reported as skipped during *setup* and never produces a call phase at all, so the
            # call-phase branch would leave it as "unknown" -- indistinguishable from a test that
            # genuinely never reported, and alarming in the comparison for no reason.
            record.outcome = "skipped"
        elif report.when == "call":
            record.outcome = report.outcome
        elif report.outcome == "failed":
            # A setup/teardown error never produces a call phase; without this the test would be
            # written out as "unknown" and read as missing rather than broken.
            record.outcome = "error"
            record.longrepr = str(report.longrepr)[:2000]

        if report.outcome == "failed" and report.when == "call":
            record.longrepr = str(report.longrepr)[:2000]

    def add_context(self, key: str, value: Any) -> None:  # noqa: ANN401 - free-form manifest data
        self.context[key] = value

    def payload(self) -> dict[str, Any]:
        return {
            "infrahub_version": self.infrahub_version,
            "started_at": self.started_wall,
            "wall_clock_seconds": round(time.monotonic() - self.started_at, 3),
            "host": {
                "platform": platform.platform(),
                "python": platform.python_version(),
                "cpu_count": os.cpu_count(),
            },
            "context": self.context,
            "tests": [
                {
                    "nodeid": record.nodeid,
                    "outcome": record.outcome,
                    "total_seconds": round(record.total, 3),
                    "durations": {phase: round(value, 3) for phase, value in record.durations.items()},
                    "longrepr": record.longrepr,
                }
                for record in sorted(self.records.values(), key=lambda item: item.nodeid)
            ],
        }

    def write(self) -> None:
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self.output_path.write_text(json.dumps(self.payload(), indent=2) + "\n", encoding="utf-8")


_recorder: PerfRecorder | None = None


def build_recorder() -> PerfRecorder | None:
    """Install and return a recorder when ``AI_DC_PERF_OUT`` is set, otherwise None (feature off)."""
    global _recorder  # noqa: PLW0603
    output = os.environ.get(ENV_OUTPUT_PATH)
    _recorder = (
        PerfRecorder(
            output_path=Path(output),
            infrahub_version=os.environ.get("INFRAHUB_BASE_VERSION", "unset"),
        )
        if output
        else None
    )
    return _recorder


def get_recorder() -> PerfRecorder | None:
    """Return the session recorder, or None when capture is off.

    Lets fixtures annotate the run manifest without importing the conftest that owns the session
    hooks.
    """
    return _recorder
