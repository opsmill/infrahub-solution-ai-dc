"""Load generator that validates Infrahub's priority-aware API backpressure.

The script drives the GraphQL API with three independent, constant-rate streams of
requests — one per admission priority (``high``/``medium``/``low``) — for a fixed
duration, then reports how each priority fared. Each stream tags its requests with the
``X-Priority`` header the admission middleware classifies on, so shedding under load can
be observed per class: the whole point of the feature is that ``high`` keeps flowing
while ``low`` sheds first.

Load is generated open-loop: requests are fired at their target arrival rate regardless
of how fast the server responds. This is deliberate. A closed-loop generator (wait for a
response before sending the next request) self-throttles the moment the server slows,
which hides the very shedding this script exists to measure.

The GraphQL queries themselves live in a separate YAML file (see the ``--queries``
argument and the bundled ``rate_limit_queries.example.yml``), so the load profile can be
changed without editing this script.

Outputs (written to ``--output-dir``):
  - a text summary printed to stdout and saved as ``summary.txt``
  - ``samples.csv`` with one row per request for further analysis
  - ``report.png`` with throughput, shed rate, and response time over time

Run it against a local stack:

    uv run python utilities/rate_limit_loadtest.py \\
        --url http://localhost:8000 --token "$INFRAHUB_API_TOKEN" \\
        --queries utilities/rate_limit_queries.example.yml --duration 30
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import math
import os
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import httpx
import yaml

# The priority tiers, in the order the middleware sheds them (high sheds last). Kept as a
# tuple so iteration order in the report is stable and matches the admission semantics.
PRIORITIES: tuple[str, ...] = ("high", "medium", "low")

# Requests are grouped into one-second buckets for the time series. One second is the
# coarsest bucket that still shows the ramp into shedding on a typical 30-120s run.
BUCKET_SECONDS: float = 1.0

# The shed status the admission middleware answers with when it rejects a request.
HTTP_TOO_MANY_REQUESTS: int = 429
HTTP_OK_RANGE: range = range(200, 300)


@dataclass(frozen=True)
class TierConfig:
    """A single priority stream: its target arrival rate and the queries it rotates through."""

    priority: str
    rate: float
    queries: list[dict[str, object]]


@dataclass(frozen=True)
class Sample:
    """One observed request outcome.

    ``offset`` is seconds since the run started (used for bucketing). ``latency`` is the
    wall-clock request duration in seconds. ``status`` is the HTTP status, or ``None`` when
    the request never got a response (connection error, timeout).
    """

    priority: str
    offset: float
    latency: float
    status: int | None
    outcome: str  # "ok" | "shed" | "error"


@dataclass
class Counters:
    """Live tallies for one priority, updated as samples arrive."""

    offered: int = 0
    ok: int = 0
    shed: int = 0
    error: int = 0
    client_overload: int = 0
    latencies_ok: list[float] = field(default_factory=list)


def load_queries(path: Path, rate_overrides: dict[str, float | None]) -> list[TierConfig]:
    """Parse the queries YAML into one :class:`TierConfig` per priority present.

    The file maps each priority to a ``rate`` (requests/second) and a list of ``queries``,
    each with a ``query`` string and optional ``variables``. A CLI ``--rate-<tier>`` value,
    when given, overrides the file's rate. A tier with rate ``0`` is skipped entirely.

    Raises:
        ValueError: the file is malformed, names an unknown priority, or a query is missing.

    """
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: top level must be a mapping of priority -> config")

    tiers: list[TierConfig] = []
    for priority in PRIORITIES:
        if priority not in raw:
            continue
        section = raw[priority]
        if not isinstance(section, dict):
            raise ValueError(f"{path}: '{priority}' must be a mapping with 'rate' and 'queries'")

        queries = section.get("queries")
        if not isinstance(queries, list) or not queries:
            raise ValueError(f"{path}: '{priority}.queries' must be a non-empty list")
        for entry in queries:
            if not isinstance(entry, dict) or not entry.get("query"):
                raise ValueError(f"{path}: every entry in '{priority}.queries' needs a 'query' field")

        override = rate_overrides.get(priority)
        rate = float(override) if override is not None else float(section.get("rate", 0))
        if rate <= 0:
            continue
        tiers.append(TierConfig(priority=priority, rate=rate, queries=queries))

    unknown = set(raw) - set(PRIORITIES)
    if unknown:
        raise ValueError(f"{path}: unknown priority section(s): {', '.join(sorted(unknown))}")
    if not tiers:
        raise ValueError(f"{path}: no priority has a positive rate; nothing to send")
    return tiers


def _classify(status: int | None) -> str:
    """Map an HTTP status (or ``None`` for no response) to an outcome bucket."""
    if status is None:
        return "error"
    if status == HTTP_TOO_MANY_REQUESTS:
        return "shed"
    if status in HTTP_OK_RANGE:
        return "ok"
    return "error"


class LoadTest:
    """Runs the priority streams concurrently and collects one :class:`Sample` per request.

    The client, endpoint, and duration are fixed for a run and injected at construction; the
    tier list is the transient work driven through :meth:`run`. In-flight requests per tier
    are capped so a slow or shedding server cannot let pending tasks grow without bound on the
    load machine — requests that would breach the cap are recorded as ``client_overload`` and
    reported, never silently dropped.
    """

    def __init__(
        self,
        *,
        client: httpx.AsyncClient,
        endpoint: str,
        token: str | None,
        duration: float,
        max_in_flight_per_tier: int,
    ) -> None:
        self._client = client
        self._endpoint = endpoint
        self._token = token
        self._duration = duration
        self._max_in_flight = max_in_flight_per_tier
        self._samples: list[Sample] = []
        self._start: float = 0.0

    async def run(self, tiers: list[TierConfig]) -> list[Sample]:
        """Fire all tiers for the configured duration and return every collected sample."""
        self._start = time.perf_counter()
        await asyncio.gather(*(self._drive_tier(tier) for tier in tiers))
        return self._samples

    async def _drive_tier(self, tier: TierConfig) -> None:
        """Open-loop scheduler for one priority: spawn a request every ``1/rate`` seconds.

        The next-send deadline advances by a fixed interval rather than sleeping ``interval``
        after each spawn, so scheduling drift does not lower the effective rate. Spawned
        requests are fire-and-forget tasks; the scheduler never waits on a response.
        """
        interval = 1.0 / tier.rate
        in_flight: set[asyncio.Task[None]] = set()
        deadline = time.perf_counter()
        index = 0

        while time.perf_counter() - self._start < self._duration:
            now = time.perf_counter()
            if now < deadline:
                await asyncio.sleep(deadline - now)
            deadline += interval

            query = tier.queries[index % len(tier.queries)]
            index += 1

            if len(in_flight) >= self._max_in_flight:
                # The load machine cannot hold more outstanding requests for this tier. Record
                # it honestly so the report shows the client — not the server — was the limit.
                self._samples.append(
                    Sample(
                        priority=tier.priority,
                        offset=now - self._start,
                        latency=0.0,
                        status=None,
                        outcome="client_overload",
                    )
                )
                continue

            task = asyncio.create_task(self._send(tier.priority, query))
            in_flight.add(task)
            task.add_done_callback(in_flight.discard)

        if in_flight:
            await asyncio.gather(*in_flight, return_exceptions=True)

    async def _send(self, priority: str, query: dict[str, object]) -> None:
        """Send one GraphQL request and append its outcome sample."""
        headers = {"X-Priority": priority}
        if self._token:
            headers["X-INFRAHUB-KEY"] = self._token
        payload: dict[str, object] = {"query": query["query"]}
        if query.get("variables"):
            payload["variables"] = query["variables"]

        sent = time.perf_counter()
        offset = sent - self._start
        try:
            response = await self._client.post(self._endpoint, json=payload, headers=headers)
            status: int | None = response.status_code
        except httpx.HTTPError:
            status = None
        latency = time.perf_counter() - sent
        self._samples.append(
            Sample(priority=priority, offset=offset, latency=latency, status=status, outcome=_classify(status))
        )


def _percentile(values: list[float], pct: float) -> float:
    """Return the ``pct`` percentile (0-100) of ``values`` via nearest-rank; 0 if empty."""
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(0, min(len(ordered) - 1, math.ceil(pct / 100 * len(ordered)) - 1))
    return ordered[rank]


def summarize(samples: list[Sample]) -> dict[str, Counters]:
    """Fold the raw samples into per-priority counters."""
    counters: dict[str, Counters] = {p: Counters() for p in PRIORITIES}
    for sample in samples:
        counter = counters[sample.priority]
        if sample.outcome == "client_overload":
            counter.client_overload += 1
            continue
        counter.offered += 1
        if sample.outcome == "ok":
            counter.ok += 1
            counter.latencies_ok.append(sample.latency)
        elif sample.outcome == "shed":
            counter.shed += 1
        else:
            counter.error += 1
    return counters


def format_summary(counters: dict[str, Counters], duration: float) -> str:
    """Render the per-priority summary table as text."""
    header = (
        f"{'priority':<9} {'offered':>8} {'2xx':>7} {'429':>7} {'err':>5} {'shed%':>7} "
        f"{'p50 ms':>8} {'p95 ms':>8} {'p99 ms':>8} {'max ms':>8}"
    )
    lines: list[str] = [f"Rate-limit load test — {duration:.0f}s", "", header, "-" * len(header)]
    for priority in PRIORITIES:
        c = counters[priority]
        if c.offered == 0 and c.client_overload == 0:
            continue
        shed_pct = (c.shed / c.offered * 100) if c.offered else 0.0
        lat = [v * 1000 for v in c.latencies_ok]
        lines.append(
            f"{priority:<9} {c.offered:>8} {c.ok:>7} {c.shed:>7} {c.error:>5} {shed_pct:>6.1f}% "
            f"{_percentile(lat, 50):>8.1f} {_percentile(lat, 95):>8.1f} "
            f"{_percentile(lat, 99):>8.1f} {(max(lat) if lat else 0.0):>8.1f}"
        )
        if c.client_overload:
            lines.append(f"{'':<9} (client_overload dropped before send: {c.client_overload})")
    lines.extend(("", "Response-time percentiles cover 2xx responses only (429s are shed near-instantly)."))
    return "\n".join(lines)


def write_csv(samples: list[Sample], path: Path) -> None:
    """Write one row per request for offline analysis."""
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["priority", "offset_s", "latency_ms", "status", "outcome"])
        for s in samples:
            writer.writerow(
                [
                    s.priority,
                    f"{s.offset:.4f}",
                    f"{s.latency * 1000:.2f}",
                    "" if s.status is None else s.status,
                    s.outcome,
                ]
            )


def _bucketize(samples: list[Sample], duration: float) -> tuple[list[float], dict[str, dict[str, list[float]]]]:
    """Group samples into per-second buckets, returning bucket centers and per-priority series.

    Returns ``(times, series)`` where ``series[priority]`` has ``offered``/``ok``/``shed`` counts
    per bucket and ``p95`` response time (ms) per bucket for 2xx responses.
    """
    n_buckets = max(1, math.ceil(duration / BUCKET_SECONDS))
    times = [(i + 0.5) * BUCKET_SECONDS for i in range(n_buckets)]

    def _empty() -> dict[str, list[float]]:
        return {
            "offered": [0.0] * n_buckets,
            "ok": [0.0] * n_buckets,
            "shed": [0.0] * n_buckets,
            "p95": [0.0] * n_buckets,
        }

    series: dict[str, dict[str, list[float]]] = {p: _empty() for p in PRIORITIES}
    latencies: dict[str, dict[int, list[float]]] = {p: defaultdict(list) for p in PRIORITIES}

    for s in samples:
        if s.outcome == "client_overload":
            continue
        idx = min(n_buckets - 1, int(s.offset / BUCKET_SECONDS))
        bucket = series[s.priority]
        bucket["offered"][idx] += 1
        if s.outcome == "ok":
            bucket["ok"][idx] += 1
            latencies[s.priority][idx].append(s.latency * 1000)
        elif s.outcome == "shed":
            bucket["shed"][idx] += 1

    for priority in PRIORITIES:
        for idx, values in latencies[priority].items():
            series[priority]["p95"][idx] = _percentile(values, 95)
    return times, series


def write_graph(samples: list[Sample], duration: float, path: Path) -> None:
    """Render throughput, shed rate, and response time over time to a PNG.

    Uses the non-interactive Agg backend so it runs headless (CI, remote box). Imported
    lazily so the rest of the tool works even if matplotlib is unavailable.
    """
    import matplotlib as mpl  # noqa: PLC0415

    mpl.use("Agg")
    import matplotlib.pyplot as plt  # noqa: PLC0415

    times, series = _bucketize(samples, duration)
    colors = {"high": "#2ca02c", "medium": "#ff7f0e", "low": "#d62728"}

    fig, (ax_tp, ax_shed, ax_lat) = plt.subplots(3, 1, figsize=(11, 12), sharex=True)

    # Panel 1: aggregate requests/s — offered vs returned (2xx) vs shed (429).
    offered = [sum(series[p]["offered"][i] for p in PRIORITIES) for i in range(len(times))]
    returned = [sum(series[p]["ok"][i] for p in PRIORITIES) for i in range(len(times))]
    shed = [sum(series[p]["shed"][i] for p in PRIORITIES) for i in range(len(times))]
    ax_tp.plot(times, offered, label="offered", color="#1f77b4", linewidth=2)
    ax_tp.plot(times, returned, label="returned (2xx)", color="#2ca02c", linewidth=2)
    ax_tp.plot(times, shed, label="shed (429)", color="#d62728", linewidth=2, linestyle="--")
    ax_tp.fill_between(times, returned, alpha=0.12, color="#2ca02c")
    ax_tp.set_ylabel("requests / s")
    ax_tp.set_title("Requests over time: offered vs returned vs shed (all priorities)")
    ax_tp.legend(loc="upper left")
    ax_tp.grid(True, alpha=0.3)

    # Panel 2: shed/s per priority — shows high sheds last.
    for priority in PRIORITIES:
        if any(series[priority]["offered"]):
            ax_shed.plot(times, series[priority]["shed"], label=f"{priority} 429/s", color=colors[priority])
    ax_shed.set_ylabel("shed (429) / s")
    ax_shed.set_title("Shed rate by priority")
    ax_shed.legend(loc="upper left")
    ax_shed.grid(True, alpha=0.3)

    # Panel 3: p95 response time per priority (2xx only).
    for priority in PRIORITIES:
        if any(series[priority]["offered"]):
            ax_lat.plot(times, series[priority]["p95"], label=f"{priority} p95", color=colors[priority])
    ax_lat.set_ylabel("p95 response time (ms)")
    ax_lat.set_xlabel("time (s)")
    ax_lat.set_title("Response time by priority (2xx only)")
    ax_lat.legend(loc="upper left")
    ax_lat.grid(True, alpha=0.3)

    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--url",
        default=os.environ.get("INFRAHUB_ADDRESS", "http://localhost:8000"),
        help="Base URL of the Infrahub API (default: $INFRAHUB_ADDRESS or http://localhost:8000)",
    )
    parser.add_argument("--branch", default="main", help="Branch to target in the GraphQL path (default: main)")
    parser.add_argument(
        "--token",
        default=os.environ.get("INFRAHUB_API_TOKEN"),
        help="API token sent as X-INFRAHUB-KEY (default: $INFRAHUB_API_TOKEN)",
    )
    parser.add_argument("--queries", type=Path, required=True, help="Path to the queries YAML file")
    parser.add_argument("--duration", type=float, default=30.0, help="Run duration in seconds (default: 30)")
    parser.add_argument("--rate-high", type=float, default=None, help="Override high-priority requests/second")
    parser.add_argument("--rate-medium", type=float, default=None, help="Override medium-priority requests/second")
    parser.add_argument("--rate-low", type=float, default=None, help="Override low-priority requests/second")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("rate_limit_report"),
        help="Directory for summary.txt, samples.csv, report.png (default: ./rate_limit_report)",
    )
    parser.add_argument("--timeout", type=float, default=30.0, help="Per-request timeout in seconds (default: 30)")
    parser.add_argument(
        "--max-in-flight",
        type=int,
        default=2000,
        help="Per-priority cap on outstanding requests on the load machine (default: 2000)",
    )
    parser.add_argument("--no-graph", action="store_true", help="Skip PNG generation")
    return parser.parse_args(argv)


async def _run_load(args: argparse.Namespace, tiers: list[TierConfig], endpoint: str) -> list[Sample]:
    """Drive every tier against ``endpoint`` for the configured duration and return the samples."""
    limits = httpx.Limits(max_connections=None, max_keepalive_connections=200)
    async with httpx.AsyncClient(timeout=args.timeout, limits=limits) as client:
        test = LoadTest(
            client=client,
            endpoint=endpoint,
            token=args.token,
            duration=args.duration,
            max_in_flight_per_tier=args.max_in_flight,
        )
        return await test.run(tiers)


def main() -> int:
    args = parse_args()
    tiers = load_queries(
        args.queries,
        {"high": args.rate_high, "medium": args.rate_medium, "low": args.rate_low},
    )

    endpoint = f"{args.url.rstrip('/')}/graphql/{args.branch}"
    print(f"Target: {endpoint}")
    print(f"Duration: {args.duration:.0f}s   Auth: {'yes' if args.token else 'NO (anonymous)'}")
    for tier in tiers:
        print(
            f"  {tier.priority:<7} {tier.rate:>7.1f} req/s   {len(tier.queries)} quer"
            f"{'y' if len(tier.queries) == 1 else 'ies'}"
        )
    print()

    samples = asyncio.run(_run_load(args, tiers, endpoint))

    summary = format_summary(summarize(samples), args.duration)
    print(summary)

    output_dir: Path = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "summary.txt").write_text(summary + "\n", encoding="utf-8")
    write_csv(samples, output_dir / "samples.csv")
    print(f"\nWrote {output_dir / 'summary.txt'}")
    print(f"Wrote {output_dir / 'samples.csv'} ({len(samples)} rows)")

    if not args.no_graph:
        graph_path = output_dir / "report.png"
        write_graph(samples, args.duration, graph_path)
        print(f"Wrote {graph_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
