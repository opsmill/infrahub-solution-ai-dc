# Rate-limit load test

`rate_limit_loadtest.py` drives the Infrahub GraphQL API with three independent,
constant-rate streams of requests — one per admission priority (`high` / `medium` /
`low`) — for a fixed duration, then reports how each priority fared. It exists to validate
the priority-aware API backpressure: under load, `high` should keep flowing while `low`
sheds (HTTP `429`) first.

## Why open-loop

Requests are fired at their target arrival rate regardless of how fast the server
responds. A closed-loop generator (wait for a response before sending the next request)
self-throttles the moment the server slows, which hides the shedding this script measures.

## Queries file

The GraphQL queries live in a separate YAML file so the load profile can change without
editing the script. Each top-level key is a priority with a `rate` (requests/second) and a
list of `queries`; the header `X-Priority: <tier>` is set automatically per stream. See
[`rate_limit_queries.example.yml`](rate_limit_queries.example.yml).

```yaml
high:
  rate: 20
  queries:
    - name: branch_list
      query: |
        query { Branch { name } }
```

Grade the query cost across tiers (cheap for `high`, heavier for `low`) so the streams put
different *real* pressure on the server, not just a different header.

## Run

```bash
uv run python utilities/rate_limit_loadtest.py \
    --url http://localhost:8000 \
    --token "$INFRAHUB_API_TOKEN" \
    --queries utilities/rate_limit_queries.example.yml \
    --duration 30
```

Per-tier rates from the file can be overridden with `--rate-high`, `--rate-medium`,
`--rate-low` (set to `0` to disable a stream). The server must be started with backpressure
enabled (`INFRAHUB_API_BACKPRESSURE_ENABLED=true`, the default) for shedding to occur.

## Outputs

Written to `--output-dir` (default `./rate_limit_report`):

- **`summary.txt`** — per-priority table: offered, `2xx`, `429`, error, shed %, and
  response-time percentiles (p50/p95/p99/max over `2xx` responses only).
- **`samples.csv`** — one row per request (`priority`, `offset_s`, `latency_ms`, `status`,
  `outcome`) for offline analysis.
- **`report.png`** — three stacked panels over time: aggregate offered vs returned vs shed
  throughput, shed rate by priority, and p95 response time by priority.
