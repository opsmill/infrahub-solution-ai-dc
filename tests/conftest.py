"""Test-session bootstrap shared by the unit and integration suites.

Loaded before ``pytest_sessionstart`` (pytest imports the conftest of the initial ``testpaths``
argument during startup), which is the only window in which the guard below can take effect.
"""

from __future__ import annotations

import psutil

# ``infrahub_testcontainers``' pytest plugin builds a host profile in ``pytest_sessionstart`` and
# calls ``psutil.cpu_freq()`` unguarded (infrahub_testcontainers/host.py). On Apple Silicon that
# raises ``RuntimeError: 'voltage-states1-sram' property not found`` from psutil's macOS backend,
# which surfaces as a pytest INTERNALERROR before a single test is collected -- taking the whole
# suite down, unit tests included, purely to record a CPU frequency.
#
# Report the frequency as unavailable instead of crashing. Nothing in the suite asserts on it; it
# only feeds the performance-profile output.
_original_cpu_freq = psutil.cpu_freq


def _cpu_freq_or_none(*args: object, **kwargs: object) -> object:
    try:
        return _original_cpu_freq(*args, **kwargs)  # type: ignore[arg-type]
    except (RuntimeError, OSError, NotImplementedError, AttributeError):
        return None


psutil.cpu_freq = _cpu_freq_or_none  # type: ignore[assignment]
