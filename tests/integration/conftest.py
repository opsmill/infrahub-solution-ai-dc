import os
import subprocess  # noqa: S404
from pathlib import Path
from typing import Any

import pytest
from infrahub_sdk.yaml import SchemaFile
from infrahub_testcontainers import __version__ as testcontainers_version

from tests.integration.repo_source import describe_adaptations, prepare_repo_source
from tests.perf import get_recorder

CURRENT_DIRECTORY = Path(__file__).parent.resolve()

# The testcontainers stack needs two project-specific settings. They are applied at import time so
# they land before ``infrahub_testcontainers`` snapshots the environment, and via ``setdefault`` so
# an explicit env var still wins:
#
# 1. The default stack runs the vanilla ``opsmill/infrahub`` image, which has no
#    ``infrahub_solution_ai_dc`` module — every transform/generator import fails during repository
#    sync. Point it at the image ``inv build`` produces (and skip the registry pull, it is local).
# 2. ``docker compose up --wait`` fails on a project containing a zero-replica service, reporting it
#    as a missing dependency — a Compose bug (docker/compose#13899), not a stack problem. The stack
#    declares ``task-manager-background-svc`` with ``replicas: 0`` and nothing depends on it, so
#    scheduling one replica is a harmless workaround. Drop it once Compose ships the fix.
#
# INFRAHUB_BASE_VERSION is the single knob that selects the Infrahub version under test:
#
#     INFRAHUB_BASE_VERSION=1.10.6 uv run pytest tests/integration
#
# It swaps the Infrahub *application* image only. The surrounding infrastructure (Neo4j, RabbitMQ,
# Redis) is pinned by the installed ``infrahub-testcontainers`` package's bundled compose, so both
# sides of a version comparison share one infra matrix. That isolates the application version, which
# is what a release comparison wants, but it is not a faithful reproduction of an older deployment.
#
# Nothing else needs changing to test an older release: ``repo_source.prepare_repo_source`` adapts
# the copy of the repo that the stack clones (see that module), so the working tree stays untouched.
TESTING_IMAGE = "opsmill/infrahub-solution-ai-dc"
TESTING_IMAGE_VERSION = os.environ.get("INFRAHUB_BASE_VERSION", "1.11.0b0")

os.environ.setdefault("INFRAHUB_TESTING_DOCKER_IMAGE", TESTING_IMAGE)
os.environ.setdefault("INFRAHUB_TESTING_IMAGE_VERSION", TESTING_IMAGE_VERSION)
os.environ.setdefault("INFRAHUB_TESTING_DOCKER_PULL", "false")
os.environ.setdefault("INFRAHUB_TESTING_TASKMGR_BACKGROUND_SVC_REPLICAS", "1")


@pytest.fixture(scope="session", autouse=True)
def require_testing_image() -> None:
    """Fail loud (naming the fix) when the local image the stack needs has not been built yet."""
    image = f"{os.environ['INFRAHUB_TESTING_DOCKER_IMAGE']}:{os.environ['INFRAHUB_TESTING_IMAGE_VERSION']}"
    inspect = subprocess.run(  # noqa: S603
        ["docker", "image", "inspect", image],  # noqa: S607
        capture_output=True,
        check=False,
    )
    if inspect.returncode != 0:
        pytest.fail(f"Docker image {image!r} is missing; run `inv build` before the integration tests")

    # Stamp the run manifest so a results file always says which image produced it and how the repo
    # was adapted -- otherwise two JSON files are indistinguishable once the env var is gone.
    recorder = get_recorder()
    if recorder is not None:
        recorder.add_context("image", image)
        recorder.add_context("testcontainers_version", testcontainers_version)
        recorder.add_context("repo_adaptations", list(describe_adaptations(TESTING_IMAGE_VERSION)))


@pytest.fixture
def root_directory() -> Path:
    """
    Return the path of the root directory of the repository.
    """
    return CURRENT_DIRECTORY.parent.parent


@pytest.fixture(scope="session")
def repo_source_directory(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The repo tree the stack clones, adapted to the version under test.

    Session-scoped: the adaptation depends only on INFRAHUB_BASE_VERSION, so the four test classes
    share one prepared copy instead of each paying to build its own. ``GitRepo`` still makes its own
    per-class copy from this one, so the classes stay isolated from each other.

    Use this -- not ``root_directory`` -- as ``GitRepo(src_directory=...)``. Passing the repo root
    directly serves ``.infrahub.yml`` verbatim, which an Infrahub older than 1.11 rejects outright.
    """
    root = CURRENT_DIRECTORY.parent.parent
    destination = tmp_path_factory.mktemp("repo_source") / "infrahub-solution-ai-dc"
    return prepare_repo_source(root_directory=root, destination=destination, version=TESTING_IMAGE_VERSION)


@pytest.fixture
def schemas_directory(root_directory: Path) -> Path:
    return root_directory / "schemas"


@pytest.fixture
def schemas(schemas_directory: Path) -> list[dict[str, Any]]:
    schema_files = SchemaFile.load_from_disk(paths=[schemas_directory])
    return [item.content for item in schema_files if item.content]
