"""The shared package must be importable on an Infrahub image that does not have it installed.

Infrahub imports ``generators`` and ``transforms`` from a repository checkout and does not put ``src/`` on
``sys.path``. Each package's ``__init__`` adds it. These tests run a fresh interpreter without ``site``, so the
copy installed in the development environment cannot hide a missing path.
"""

import subprocess  # noqa: S404
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

SCRIPT = """
import importlib.util
import sys

assert importlib.util.find_spec("infrahub_solution_ai_dc") is None, "the package must not be installed here"

spec = importlib.util.spec_from_file_location(sys.argv[1], sys.argv[2] + "/__init__.py", submodule_search_locations=[sys.argv[2]])
module = importlib.util.module_from_spec(spec)
sys.modules[sys.argv[1]] = module
spec.loader.exec_module(module)

found = importlib.util.find_spec("infrahub_solution_ai_dc")
assert found is not None, "the package is not importable after importing " + sys.argv[1]
print(found.origin)
"""


@pytest.mark.parametrize("directory", ["generators", "transforms"])
def test_package_is_importable_from_the_checkout(directory: str) -> None:
    result = subprocess.run(  # noqa: S603
        [sys.executable, "-S", "-c", SCRIPT, f"commits.sha.{directory}", str(ROOT / directory)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == str(ROOT / "src" / "infrahub_solution_ai_dc" / "__init__.py")
