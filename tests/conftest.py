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

# ``infrahub_testcontainers``' pytest plugin builds a host profile in ``pytest_sessionstart`` and
# calls ``psutil.cpu_freq()`` unguarded (infrahub_testcontainers/host.py). On Apple Silicon that
# raises ``RuntimeError: 'voltage-states1-sram' property not found`` from psutil's macOS backend,
# which surfaces as a pytest INTERNALERROR before a single test is collected -- taking the whole
# suite down, unit tests included, purely to record a CPU frequency.
#
# Report the frequency as unavailable instead of crashing. ``get_system_stats`` already writes
# ``None`` for the three frequency fields when the call returns falsy, and nothing in the suite
# asserts on them; they only feed the performance-profile output.
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
        except (RuntimeError, OSError, NotImplementedError, AttributeError):
            return None

    psutil.cpu_freq = _cpu_freq_or_none  # type: ignore[assignment]
