#!/usr/bin/env bash
# Run the integration suite against two full Infrahub stacks and diff the results.
#
#   ./dev/compare_versions.sh 1.10.6 1.11.0b1
#
# "Full stack" means both halves move together for each side:
#
#   * the Infrahub application image  (INFRAHUB_BASE_VERSION -> the image `docker compose build` tags)
#   * the surrounding stack definition (infrahub-testcontainers, which ships the compose file that
#     pins Neo4j/RabbitMQ/Redis/Postgres and the container ulimits)
#
# Swapping only the application image -- what a plain `INFRAHUB_BASE_VERSION=x pytest` does -- leaves
# the stack definition at whatever the project lockfile holds, so a stack-level change between
# releases is invisible. Those changes are real: 1.11.0b1 raises the nofile ceiling to 1048576 on the
# database, server and worker, adds a Neo4j bolt thread-pool knob, and adds a merge grace period.
#
# Everything else is pinned identically on both sides (infrahub-sdk, pytest, pytest-asyncio), so the
# stack is the only variable. The runs are sequential on purpose: running them concurrently would have
# them contend for the same cores and disk and make every timing meaningless.
set -euo pipefail

BASELINE="${1:-1.10.6}"
CANDIDATE="${2:-1.11.0b1}"
REPORT="${3:-perf-results/comparison.md}"

# Pinned so that infrahub-testcontainers is the only thing that differs between the two environments.
# The SDK is the *client*; holding it constant keeps the test code identical across both runs.
SDK_VERSION="1.23.0b0"
PYTEST_VERSION="8.4.1"
PYTEST_ASYNCIO_VERSION="1.1.0"

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"
mkdir -p perf-results

for version in "$BASELINE" "$CANDIDATE"; do
  venv=".venv-tc-${version}"

  echo "==> Building the project image for ${version}"
  INFRAHUB_BASE_VERSION="$version" docker compose build

  echo "==> Preparing ${venv} (infrahub-testcontainers==${version})"
  uv venv --python 3.12 "$venv" >/dev/null
  VIRTUAL_ENV="$venv" uv pip install -q \
    "infrahub-sdk[all]==${SDK_VERSION}" \
    "infrahub-testcontainers==${version}" \
    "pytest==${PYTEST_VERSION}" \
    "pytest-asyncio==${PYTEST_ASYNCIO_VERSION}" \
    pyyaml packaging invoke -e .

  echo "==> Running the integration suite against ${version}"
  # `|| true`: a failing suite is a *result* of the comparison. Aborting here would throw away the
  # timings and, worse, skip the second version entirely -- leaving nothing to compare.
  INFRAHUB_BASE_VERSION="$version" AI_DC_PERF_OUT="perf-results/${version}.json" \
    "${venv}/bin/pytest" tests/integration -v || true
done

echo "==> Comparing"
# The script exits non-zero when it finds regressions; that is the signal, not a driver failure.
uv run python dev/compare_runs.py \
  "perf-results/${BASELINE}.json" "perf-results/${CANDIDATE}.json" -o "$REPORT" || true

echo
echo "Report written to ${REPORT}"
