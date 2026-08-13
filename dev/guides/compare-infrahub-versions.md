# Compare two Infrahub versions

How to run this repository's integration suite against two Infrahub releases and diff the results —
for release qualification, upgrade regression hunting, or investigating "did this get slower?".

## TL;DR

```bash
inv compare-versions --baseline=1.10.6 --candidate=1.11.0b1   # or: ./dev/compare_versions.sh 1.10.6 1.11.0b1
```

That builds the project image for each version, builds a matching virtualenv per version, runs
`tests/integration` against each **sequentially**, and writes `perf-results/comparison.md`. The
comparison exits non-zero when a test that passed on the baseline no longer passes on the candidate.

To drive one side only, swapping the application image but not the surrounding stack (faster; see
[Two levels of comparison](#two-levels-of-comparison) for what that misses):

```bash
inv test-version --version=1.11.0b1              # -> perf-results/1.11.0b1.json
```

Or without invoke, which is all that task does:

```bash
INFRAHUB_BASE_VERSION=1.10.6 AI_DC_PERF_OUT=perf-results/1.10.6.json uv run pytest tests/integration
uv run python dev/compare_runs.py perf-results/1.10.6.json perf-results/1.11.0b1.json
```

## The one knob

`INFRAHUB_BASE_VERSION` selects the version under test, everywhere: the `Dockerfile` build arg, the
image tag in `docker-compose.override.yml`, and the image the testcontainers stack runs
(`tests/integration/conftest.py`). **No file in the working tree needs editing to test an older
release** — see the next section for how that is kept true.

Build the image before running, or the suite fails fast naming the fix (`require_testing_image`):

```bash
INFRAHUB_BASE_VERSION=1.10.6 docker compose build
```

## Testing a release older than the repo targets

`.infrahub.yml` uses `watch:`, which does not exist before infrahub-sdk 1.23.0b0 (shipped with
Infrahub 1.11). `InfrahubRepositoryConfig` forbids extra keys, so an older server rejects the whole
file and repository sync fails with *"Extra inputs are not permitted"* — the repo never imports and
every downstream test fails for a reason that has nothing to do with the release being evaluated.

`tests/integration/repo_source.py` handles this. The stack does not clone the working tree; it clones
a prepared copy, and that copy is adapted to the target version — `watch:` is stripped when the target
predates 1.11. Adding support for a future incompatibility means one more rule in that module, not a
branch with hand-edited config.

The same module also keeps virtualenvs and other gitignored heavyweights out of the copy. `GitRepo`
copies its source wholesale but `porcelain.add` honours `.gitignore`, so those files were never part of
the repository Infrahub is served — excluding them changes what is *copied*, never what is *served*.
Both the exclusions and the rewrite apply identically to both versions, so neither biases the
comparison.

The virtualenv exclusion is a **prefix** match (`.venv*`), and deliberately so: a full-stack comparison
creates `.venv-tc-<version>` siblings next to `.venv`, and an exact-match list quietly kept copying
those — several hundred MB per class, into a temp root that is usually tmpfs. `tests/unit/test_repo_source.py`
pins this.

## Two levels of comparison

An Infrahub release is two things, and which of them you swap decides what the comparison can see.

| | Application image | Stack definition (`infrahub-testcontainers`) |
| --- | --- | --- |
| `inv test-version` / bare `INFRAHUB_BASE_VERSION=…` | version under test | whatever the lockfile holds |
| `inv compare-versions` / `dev/compare_versions.sh` | version under test | version under test |

**Application image only** is faster and isolates the application code — useful when you already know
the infrastructure is unchanged. But it is blind to stack-level changes, and those are real. Between
1.10.6 and 1.11.0b1 the bundled compose gained:

- `ulimits: nofile 1048576` on `database`, `infrahub-server` and `task-worker` (default is 1024, which
  a wide recompute fan-out exhausts with *"[Errno 24] Too many open files"*);
- `NEO4J_server_bolt_thread__pool__max__size`, tunable to avoid
  `Neo.TransientError.Request.NoThreadsAvailable`;
- `INFRAHUB_MERGE_FAILURE_GRACE_PERIOD_SECONDS`.

A run that pins the stack definition to one version attributes none of that to the release.

**Full stack** — what `dev/compare_versions.sh` does — builds a separate virtualenv per side with
`infrahub-testcontainers` matching the application image, and pins `infrahub-sdk`, `pytest` and
`pytest-asyncio` identically across both so the stack is the only variable. Note `infrahub-testcontainers`
does not depend on `infrahub-sdk`, so the two move independently; holding the SDK constant keeps the
test code and client identical on both sides.

One caveat worth knowing when reading the compose files: the Neo4j *community* image is pinned in two
places that disagree in 1.11.0b1 — the compose default says `2026.05.0-community`, but
`PROJECT_ENV_VARIABLES` writes `NEO4J_DOCKER_IMAGE=neo4j:2025.10.1-community` into the generated
`.env`, and the `.env` wins. Both sides therefore run the same Neo4j. Check the running container
rather than trusting either default.

**Not controlled**: host load. Run nothing else heavy alongside, and never run the two versions
concurrently — they would contend for the same cores and disk. Both drivers are sequential for this
reason.

## Reading the report

**Outcome changes are the headline.** A test that went `passed -> failed` is a regression candidate;
the report inlines the failure text so you can triage without rerunning.

Before concluding that a cascade failure is a regression, check it against
`dev/knowledge/generator-cascade-troubleshooting.md`. A truncated cascade produces a half-built fabric with
no error anywhere and cannot self-heal, and its usual causes are configuration or host pressure rather
than the platform — so a single failing cascade test is not by itself evidence that the candidate
version is worse. Work through that checklist, and re-run, before reporting one.

`xfailed -> xpassed` is not a regression — it means a strict-xfail test documenting a known gap started
passing, so the gap closed and the marker should come off. The suite carries two of these by design
(the missing `LocationRack.amount_of_leafs` and `NetworkFabric` trigger rules in `triggers.yml`).

**Durations are secondary and noisier.** Read them with the shape of the suite in mind: these tests
share a class-scoped stack and are phases of one long scenario, not isolated benchmarks. Only changes
exceeding both 5s and 30% are listed, to keep startup jitter out.

**Repository sync is the noisiest measurement in the suite** and worth singling out, because it is
also the largest. Across the four classes of a single run it varies by 30–50% (one measured run:
117–160s on 1.10.6, 95–156s on 1.11.0b1). A change in its mean therefore needs repeated runs before
it means anything, even though it dominates the total. Schema load, by contrast, is stable to within a
few seconds and is the better signal if you only have one run of each.

The most meaningful timings are the tier tests in `test_generator_chain.py`
(`test_pod_tier_is_triggered_by_fabric`, `test_rack_tier_is_triggered_by_pod`). Those poll until the
cascade converges, so their duration *is* end-to-end generator convergence latency. Conversely
`test_load_schema` and `test_load_repository` measure schema convergence and repository import.

## Where the temp files go (worth setting before a long run)

The integration stacks put the git repository they serve, and any database backups, under pytest's temp
root. On many hosts `/tmp` is a **tmpfs**, i.e. RAM — this machine gives it 16 GB. Three of the four
classes now clone a repo per class and pytest keeps the last few runs' directories, so a few repeated
runs can consume gigabytes of memory rather than disk. When it fills, the failures look nothing like
their cause: `copytree` dies with `[Errno 122] Disk quota exceeded`, every test errors on an unrelated
fixture, and the host may start failing to fork.

Point the temp root at real disk before a long session:

```bash
export PYTEST_DEBUG_TEMPROOT=~/.cache/aidc-pytest-tmp   # CI sets this too
```

Two related gotchas:

- Something in the stack can create `/tmp/pytest-of-<user>` owned by **root**, after which pytest
  refuses it outright (`OSError: ... is not owned by the current user`). Remove it with `sudo` — or
  avoid it entirely by setting the temp root above.
- Cleaning that directory by hand often leaves root-owned files behind (containers write into the
  mounted repos dir as root), which breaks pytest's numbered-directory logic on the *next* run with a
  `FileNotFoundError` on a path it just tried to use. Remove the whole tree, not its contents.

## Runtime, and what drives it

Three of the four integration classes now drive the full fabric → pod → rack cascade
(`cascade.provision_fabric_cascade`), because the overlay and server-service assertions need real leaf
devices. That is the cost of covering them at all — but it means the suite is long, and roughly half
of the wall clock is *deliberate waiting* rather than measured work:

- two strict-xfail tests spend `AI_DC_GAP_TIMEOUT` (300s each) timing out, which is their expected
  outcome;
- several negative assertions hold `AI_DC_NO_CASCADE_WINDOW` (120s each) open to prove something does
  *not* happen.

Every ceiling is env-overridable, so a quicker local loop is available without editing code — e.g.
`AI_DC_GAP_TIMEOUT=120 AI_DC_NO_CASCADE_WINDOW=60 pytest tests/integration`. Lower them only with the
tradeoff in mind: a gap timeout must stay long enough to build one extra device, or adding the missing
trigger rule leaves the strict xfail still timing out and hides the fix instead of failing loudly.

Two duration caveats:

- The tests with a `stays_false` window (`test_rerunning_upstream_does_not_restamp`,
  `test_default_branch_does_not_cascade`, `test_new_fabric_has_no_automatic_dispatch`) burn a fixed
  window on purpose. Their duration is a constant, not a measurement; ignore it.
- Container startup lands in the `setup` phase of each class's first test, so that one test's duration
  is dominated by the stack coming up.

## Files

| Path | Role |
| --- | --- |
| `tests/perf.py` | Timing capture. Inert unless `AI_DC_PERF_OUT` is set, so `inv test` and CI are unaffected. |
| `tests/integration/repo_source.py` | Builds the version-adapted repo copy the stack clones. |
| `dev/compare_versions.sh` | Full-stack driver: per-version image + virtualenv, both runs, then the diff. |
| `dev/compare_runs.py` | Diffs two result files into markdown; exits non-zero on regressions. |
| `perf-results/` | Output (gitignored). `.venv-tc-*/` are the per-version environments (also gitignored). |

Each result file records the versions that produced it (`infrahub_version`, `context.image`,
`context.testcontainers_version`) so a JSON is never ambiguous once the shell that made it is gone.

The bundled `infrahub_testcontainers` performance plugin (`--performance-report`) is deliberately
**not** used: its `send_results` POSTs the payload — including environment variables — to
`--performance-result-address`, whose default is a public webhook.site URL, and it scrapes a `scraper`
service the non-cluster compose does not run. `tests/perf.py` writes a local JSON file and nothing else.
