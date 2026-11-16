"""The images that the publish workflow builds are the ones that `inv build` builds.

`.github/image-editions.json` lists them for `.github/workflows/publish-images.yml`, and `tasks.EDITIONS` lists
them for `inv build`. A deployment names the published image, so the two lists must not drift.
"""

import json
import tomllib
from pathlib import Path

import tasks

ROOT = Path(__file__).resolve().parents[2]
EDITIONS_FILE = ROOT / ".github" / "image-editions.json"


def test_published_editions_are_the_editions_of_inv_build() -> None:
    published = {edition["name"]: edition for edition in json.loads(EDITIONS_FILE.read_text(encoding="utf-8"))}

    assert set(published) == set(tasks.EDITIONS)
    for name, edition in tasks.EDITIONS.items():
        assert published[name]["base_image"] == edition["base_image"]
        assert published[name]["image"] == edition["solution_image"]
        assert published[name]["user"] == edition["image_user"]


def test_dockerfile_builds_the_community_edition_by_default() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert f"ARG INFRAHUB_BASE_IMAGE={tasks.EDITIONS[tasks.COMMUNITY]['base_image']}\n" in dockerfile
    assert f"ARG INFRAHUB_IMAGE_USER={tasks.EDITIONS[tasks.COMMUNITY]['image_user']}\n" in dockerfile


def test_workflow_version_rule_is_the_version_that_inv_build_uses() -> None:
    """The workflow reads the lock file; `inv build` reads the installed package. Both must name one version."""
    lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))
    locked = next(package["version"] for package in lock["package"] if package["name"] == "infrahub-testcontainers")

    assert locked == tasks._derived_base_version()  # noqa: SLF001


def test_workflow_passes_the_build_arguments_that_the_dockerfile_declares() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    workflow = (ROOT / ".github" / "workflows" / "publish-images.yml").read_text(encoding="utf-8")

    for argument in ("INFRAHUB_BASE_IMAGE", "INFRAHUB_BASE_VERSION", "INFRAHUB_IMAGE_USER"):
        assert f"ARG {argument}" in dockerfile
        assert f"{argument}=${{{{" in workflow
