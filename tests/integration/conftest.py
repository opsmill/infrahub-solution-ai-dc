import os
import subprocess  # noqa: S404
from pathlib import Path
from typing import Any

import pytest
from infrahub_sdk.yaml import SchemaFile

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
TESTING_IMAGE = "opsmill/infrahub-solution-ai-dc"
# Mirrors the tag docker-compose.override.yml builds, and the Dockerfile's ARG default.
#
# This is the only knob that selects the Infrahub version under test:
#
#     INFRAHUB_BASE_VERSION=1.11.0b0 uv run pytest tests/integration
#
# Two things to know when using it to compare releases:
#
# 1. It cannot usefully go below 1.11 while ``.infrahub.yml`` declares ``watch:``. That key first
#    exists in infrahub-sdk 1.23.0b0 (shipped with 1.11) and the config model forbids extra keys, so
#    an older SDK rejects the whole file and repository sync fails with "Extra inputs are not
#    permitted". A pre-1.11 baseline therefore also has to drop ``watch:``, giving up the dependency
#    closures over ``src/infrahub_solution_ai_dc/`` -- which is exactly what the parent branch of
#    this change does, so the same suite can be run on both sides of the upgrade.
# 2. This knob swaps the Infrahub *application* image only. The surrounding infrastructure (Neo4j,
#    RabbitMQ, Redis) is pinned by the installed ``infrahub-testcontainers`` package's bundled
#    compose file, so a run at any version uses the infra matrix shipped with whichever
#    testcontainers version is in the lockfile. That isolates the application version, which is what
#    a release comparison wants, but it is not a faithful reproduction of an older deployment.
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


@pytest.fixture
def root_directory() -> Path:
    """
    Return the path of the root directory of the repository.
    """
    return CURRENT_DIRECTORY.parent.parent


@pytest.fixture
def schemas_directory(root_directory: Path) -> Path:
    return root_directory / "schemas"


@pytest.fixture
def schemas(schemas_directory: Path) -> list[dict[str, Any]]:
    schema_files = SchemaFile.load_from_disk(paths=[schemas_directory])
    return [item.content for item in schema_files if item.content]
