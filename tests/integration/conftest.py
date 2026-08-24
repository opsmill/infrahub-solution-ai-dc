import os
import subprocess  # noqa: S404
from pathlib import Path
from typing import Any

import pytest
from infrahub_sdk.yaml import SchemaFile
from infrahub_testcontainers import __version__ as testcontainers_version

from tests.integration.stack_config import resolve_stack_image

CURRENT_DIRECTORY = Path(__file__).parent.resolve()

# ``custom_build=True`` is what points the stack at the locally built image rather than vanilla Infrahub.
STACK_IMAGE = resolve_stack_image(
    os.environ,
    testcontainers_version,
    repository="opsmill/infrahub-solution-ai-dc",
    custom_build=True,
)

# Set at import time, before ``infrahub_testcontainers`` snapshots the environment. The replica count
# works around docker/compose#13899: ``up --wait`` fails on a project holding a zero-replica service.
os.environ.update(STACK_IMAGE.as_env())
os.environ.setdefault("INFRAHUB_TESTING_TASKMGR_BACKGROUND_SVC_REPLICAS", "1")

TESTING_IMAGE_VERSION = STACK_IMAGE.tag


@pytest.fixture(scope="session")
def _testing_image_present() -> None:
    """Fail loud (naming the fix) when the local image the stack needs has not been built yet."""
    image = STACK_IMAGE.reference
    inspect = subprocess.run(  # noqa: S603
        ["docker", "image", "inspect", image],  # noqa: S607
        capture_output=True,
        check=False,
    )
    if inspect.returncode != 0:
        pytest.fail(f"Docker image {image!r} is missing; run `inv build` before the integration tests")


@pytest.fixture(autouse=True)
def require_testing_image(request: pytest.FixtureRequest) -> None:
    """Require the built image for anything that will start a deployment, skipping ``offline`` tests."""
    if request.node.get_closest_marker("offline"):
        return
    request.getfixturevalue("_testing_image_present")


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
