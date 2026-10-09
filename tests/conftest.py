"""Test-session bootstrap shared by the unit and integration suites.

The guard below is only useful if this module is imported before ``pytest_sessionstart``, since that
is where the crash it prevents happens. It is: pytest loads initial conftests before session start,
and this file is reached that way for every invocation the repo uses.

Measured on an affected host (pytest 8.4.1), rather than reasoned from pytest internals -- with this
file temporarily removed, both ``pytest`` and ``pytest tests`` die with INTERNALERROR before
collecting anything; with it in place both collect the full suite. So plain ``pytest`` from the repo
root is covered as well as the ``pytest tests`` that ``inv test`` and CI run, and this file does not
need to move to the repo root. Re-measure that way before concluding otherwise.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pytest

# ``infrahub_testcontainers``' pytest plugin builds a host profile in ``pytest_sessionstart`` and
# calls ``psutil.cpu_freq()`` unguarded (infrahub_testcontainers/host.py). On Apple Silicon that
# raises, and because a ``pytest_sessionstart`` failure is an INTERNALERROR the whole run dies
# before a single test is collected -- taking the unit suite down with it, purely to record a CPU
# frequency.
#
# Report the frequency as unavailable instead of crashing. ``get_system_stats`` already writes
# ``None`` for the three frequency fields when the call returns falsy, and nothing in the suite
# asserts on them; they only feed the performance-profile output.
#
# The catch below is bare ``Exception`` on purpose rather than out of laziness. A tuple naming the
# plausible-looking errors reads as the more careful choice and is the wrong one here, because the
# exception this call raises is not stable across psutil versions. Measured on one arm64 macOS host,
# calling ``psutil.cpu_freq()`` directly:
#
#     psutil 7.0.0, which uv.lock pins today
#         RuntimeError: 'voltage-states1-sram' property not found
#     psutil 7.2.2
#         SystemError: <built-in function cpu_freq> returned a result with an exception set
#
# ``SystemError`` inherits from ``Exception`` directly -- not from ``RuntimeError``, ``OSError``,
# ``NotImplementedError`` or ``AttributeError``, the tuple this file used to name. So that tuple
# happens to hold on the pinned psutil and stops holding on the next one, with no signal at review
# time and the INTERNALERROR this file exists to prevent as the failure mode. psutil is not declared
# in pyproject.toml -- the lock picks it up through infrahub-testcontainers -- so that bump arrives
# with a routine lock refresh rather than as anyone's decision. Enumerating the errors buys nothing
# to pay for that: all three frequency fields are cosmetic telemetry, so whatever the call raises is
# worth swallowing.
#
# psutil is only a transitive dependency (via infrahub-testcontainers) and only the integration
# suite needs this, so a missing psutil must not take the unit suite down at collection time.
try:
    import psutil
except ImportError:  # pragma: no cover - psutil absent means the plugin below is absent too
    pass
else:
    _original_cpu_freq = psutil.cpu_freq

    def _cpu_freq_or_none(*args: object, **kwargs: object) -> object:
        try:
            return _original_cpu_freq(*args, **kwargs)  # type: ignore[arg-type]
        except Exception:  # noqa: BLE001 - the exception type varies by psutil version; see above.
            return None

    psutil.cpu_freq = _cpu_freq_or_none  # type: ignore[assignment]


# --- version-comparison timing capture -----------------------------------------------------------
#
# Inert unless AI_DC_PERF_OUT is set, so `inv test` and CI behave exactly as before. See tests/perf.py
# for why the bundled infrahub_testcontainers performance plugin is not used instead.

from tests.perf import PerfRecorder, build_recorder

_recorder: PerfRecorder | None = None


def pytest_configure(config: pytest.Config) -> None:  # noqa: ARG001
    global _recorder  # noqa: PLW0603
    _recorder = build_recorder()


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    if _recorder is not None:
        _recorder.record_report(report)


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    if _recorder is None:
        return
    _recorder.add_context("exitstatus", int(exitstatus))
    _recorder.add_context("tests_collected", session.testscollected)
    _recorder.add_context("tests_failed", session.testsfailed)
    _recorder.write()
