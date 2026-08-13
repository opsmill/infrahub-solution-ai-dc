"""Diff two ``AI_DC_PERF_OUT`` result files: regressions first, then timings.

    uv run python dev/compare_runs.py perf-results/1.10.6.json perf-results/1.11.0b1.json

Outcome changes are the headline; durations are secondary and noisy. Read the timings as convergence
latency for the tier tests (how long the platform took to cascade) and as scenario cost elsewhere --
these tests share a class-scoped stack, so they are phases of one scenario, not isolated benchmarks.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# Below this, a duration change is treated as noise rather than reported as a movement. Both a
# relative and an absolute floor are required: 30% of a 0.5s test is meaningless, and 5s on a 600s
# convergence wait is equally so.
MIN_RELATIVE_CHANGE = 0.30
MIN_ABSOLUTE_CHANGE = 5.0

# Ranked worst-first; anything that was passing and no longer is comes out on top.
OUTCOME_SEVERITY = {"error": 0, "failed": 1, "xpassed": 2, "skipped": 3, "xfailed": 4, "passed": 5}

GOOD_OUTCOMES = {"passed", "xfailed"}


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def by_nodeid(run: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {test["nodeid"]: test for test in run["tests"]}


def short(nodeid: str) -> str:
    """Trim ``tests/integration/test_x.py::TestY::test_z`` to ``TestY::test_z``."""
    return nodeid.split("::", 1)[-1] if "::" in nodeid else nodeid


def format_delta(base: float, cand: float) -> str:
    if base <= 0:
        return f"{cand:+.1f}s"
    return f"{cand - base:+.1f}s ({(cand - base) / base:+.0%})"


def compare(baseline: dict[str, Any], candidate: dict[str, Any]) -> tuple[list[str], int]:
    """Return (report lines, number of regressions)."""
    base_tests, cand_tests = by_nodeid(baseline), by_nodeid(candidate)
    lines: list[str] = []

    base_label = baseline.get("infrahub_version", "baseline")
    cand_label = candidate.get("infrahub_version", "candidate")

    def describe(label: str, run: dict[str, Any]) -> str:
        context = run.get("context", {})
        adaptations = context.get("repo_adaptations") or ["none"]
        return (
            f"- **{label}**: {run.get('wall_clock_seconds', 0) / 60:.1f} min wall clock, "
            f"{context.get('tests_collected', '?')} collected, {context.get('tests_failed', '?')} failed, "
            f"image `{context.get('image', '?')}`, repo adaptations: {', '.join(adaptations)}"
        )

    lines.extend(
        [
            f"# Infrahub {base_label} -> {cand_label}",
            "",
            describe(base_label, baseline),
            describe(cand_label, candidate),
            "",
        ]
    )

    # --- outcomes -------------------------------------------------------------------------------
    regressions: list[str] = []
    improvements: list[str] = []
    added: list[str] = []
    for nodeid, cand in sorted(cand_tests.items(), key=lambda kv: OUTCOME_SEVERITY.get(kv[1]["outcome"], 9)):
        base = base_tests.get(nodeid)
        if base is None:
            added.append(f"- NEW `{short(nodeid)}` -> {cand['outcome']}")
            continue
        if base["outcome"] == cand["outcome"]:
            continue
        entry = f"`{short(nodeid)}`: {base['outcome']} -> {cand['outcome']}"
        # xfailed -> xpassed is a strict-xfail failure, i.e. the gap it documented was closed.
        if base["outcome"] in GOOD_OUTCOMES and cand["outcome"] not in GOOD_OUTCOMES:
            regressions.append(entry)
        else:
            improvements.append(entry)

    missing = sorted(set(base_tests) - set(cand_tests))

    lines.extend(["## Outcome changes", ""])
    lines.extend(added)
    if not regressions and not improvements and not missing and not added:
        lines.append(f"None. Every test kept its outcome across both versions ({len(cand_tests)} tests).")
    lines.extend(f"- **REGRESSION** {entry}" for entry in regressions)
    lines.extend(f"- CHANGED {entry}" for entry in improvements)
    lines.extend(
        f"- MISSING in {cand_label}: `{short(nodeid)}` (was {base_tests[nodeid]['outcome']})" for nodeid in missing
    )
    lines.append("")

    # --- failure detail -------------------------------------------------------------------------
    failed = [t for t in cand_tests.values() if t["outcome"] in {"failed", "error"} and t.get("longrepr")]
    if failed:
        lines.extend([f"## Failure detail ({cand_label})", ""])
        for test in failed:
            lines.extend(
                [
                    f"### `{short(test['nodeid'])}`",
                    "",
                    "```",
                    str(test["longrepr"]).strip()[:1200],
                    "```",
                    "",
                ]
            )

    # --- durations ------------------------------------------------------------------------------
    shared = sorted(set(base_tests) & set(cand_tests))
    movements = []
    for nodeid in shared:
        base_s = base_tests[nodeid]["total_seconds"]
        cand_s = cand_tests[nodeid]["total_seconds"]
        delta = cand_s - base_s
        if abs(delta) < MIN_ABSOLUTE_CHANGE:
            continue
        if base_s > 0 and abs(delta) / base_s < MIN_RELATIVE_CHANGE:
            continue
        movements.append((delta, nodeid, base_s, cand_s))

    lines.extend(
        [
            "## Duration changes",
            "",
            f"Only changes over {MIN_ABSOLUTE_CHANGE:.0f}s *and* {MIN_RELATIVE_CHANGE:.0%} are listed.",
            "",
        ]
    )
    if movements:
        lines.extend([f"| test | {base_label} | {cand_label} | delta |", "| --- | ---: | ---: | ---: |"])
        lines.extend(
            f"| `{short(nodeid)}` | {base_s:.1f}s | {cand_s:.1f}s | {format_delta(base_s, cand_s)} |"
            for _, nodeid, base_s, cand_s in sorted(movements, key=lambda item: -abs(item[0]))
        )
    else:
        lines.append("None above the noise floor.")

    base_total = sum(t["total_seconds"] for t in base_tests.values())
    cand_total = sum(t["total_seconds"] for t in cand_tests.values())
    lines.extend(
        [
            "",
            f"Total test time: {base_total:.0f}s -> {cand_total:.0f}s ({format_delta(base_total, cand_total)})",
            "",
        ]
    )

    return lines, len(regressions)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline", type=Path)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("-o", "--output", type=Path, help="also write the report here")
    args = parser.parse_args()

    lines, regressions = compare(load(args.baseline), load(args.candidate))
    report = "\n".join(lines)
    print(report)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(report + "\n", encoding="utf-8")

    # Non-zero exit on regressions, so this is usable as a CI gate.
    return 1 if regressions else 0


if __name__ == "__main__":
    sys.exit(main())
