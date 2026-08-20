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
TESTING_IMAGE_VERSION = os.environ.get("INFRAHUB_BASE_VERSION", "1.11.0")

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
