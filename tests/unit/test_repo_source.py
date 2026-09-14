"""Unit coverage for the repo tree handed to the integration stack.

Two properties are pinned here, and both have already broken once:

1. ``watch:`` must be stripped for a target older than 1.11, or repository sync fails outright with
   "Extra inputs are not permitted" and every integration test fails for an unrelated-looking reason.
2. Virtualenvs must never be copied. The pytest temp root lives on a 16 GB **tmpfs**, so copying them
   consumes RAM; an exact-match exclusion list kept ``.venv`` out but happily copied the sibling
   ``.venv-tc-<version>`` environments a version comparison creates, until ``copytree`` died with
   "[Errno 122] Disk quota exceeded" and the host started failing to fork.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
import yaml

from tests.integration.repo_source import (
    describe_adaptations,
    is_excluded,
    prepare_repo_source,
    strip_watch_keys,
    supports_watch_key,
)

if TYPE_CHECKING:
    from pathlib import Path


class TestSupportsWatchKey:
    @pytest.mark.parametrize(
        ("version", "supported"),
        [
            ("1.10.6", False),
            ("1.11.0b0", True),
            ("1.11.0b2", True),
            ("1.11.0", True),
            ("1.12.0", True),
        ],
    )
    def test_version_boundary(self, version: str, supported: bool) -> None:
        assert supports_watch_key(version) is supported

    @pytest.mark.parametrize("version", ["local", "stable", "develop", ""])
    def test_unparseable_versions_are_treated_as_current(self, version: str) -> None:
        """Guessing "old" would silently drop the src/ dependency closure from a branch build."""
        assert supports_watch_key(version) is True


class TestExclusions:
    @pytest.mark.parametrize(
        "name",
        [
            ".venv",
            # The regression: sibling per-version environments created by a comparison run.
            ".venv-tc-1.10.6",
            ".venv-tc-1.11.0b2",
            ".git",
            "node_modules",
            "__pycache__",
            ".mypy_cache",
            ".ruff_cache",
            ".pytest_cache",
            "perf-results",
        ],
    )
    def test_excluded(self, name: str) -> None:
        assert is_excluded(name) is True

    @pytest.mark.parametrize(
        "name",
        ["schemas", "objects", "generators", "transforms", "src", ".infrahub.yml", ".gitignore", "menus"],
    )
    def test_kept(self, name: str) -> None:
        """Everything the server actually reads has to survive the copy."""
        assert is_excluded(name) is False


class TestStripWatchKeys:
    def test_removes_watch_at_any_depth(self) -> None:
        document = {
            "generator_definitions": [{"name": "g", "watch": {"files": ["src/"]}}],
            "python_transforms": [{"name": "t", "watch": {"files": ["src/"]}}],
            "nested": {"deeper": [{"watch": {"files": ["src/"]}, "keep": 1}]},
        }
        stripped = strip_watch_keys(document)

        assert "watch" not in stripped["generator_definitions"][0]
        assert "watch" not in stripped["python_transforms"][0]
        assert "watch" not in stripped["nested"]["deeper"][0]
        # Everything else survives untouched.
        assert stripped["generator_definitions"][0]["name"] == "g"
        assert stripped["nested"]["deeper"][0]["keep"] == 1

    def test_leaves_a_document_without_watch_alone(self) -> None:
        document = {"generator_definitions": [{"name": "g"}]}
        assert strip_watch_keys(document) == document


class TestPrepareRepoSource:
    @staticmethod
    def make_repo(root: Path) -> Path:
        """A miniature repo carrying both a real file and the venvs that must not be copied."""
        (root / "schemas").mkdir(parents=True)
        (root / "schemas" / "a.yml").write_text("x: 1", encoding="utf-8")
        (root / ".infrahub.yml").write_text(
            yaml.safe_dump(
                {
                    "generator_definitions": [
                        {"name": "g", "file_path": "./g.py", "watch": {"files": ["src/infrahub_solution_ai_dc/"]}}
                    ]
                }
            ),
            encoding="utf-8",
        )
        for venv in (".venv", ".venv-tc-1.10.6", ".venv-tc-1.11.0b2"):
            (root / venv / "bin").mkdir(parents=True)
            (root / venv / "bin" / "python").write_text("binary", encoding="utf-8")
        return root

    def test_venvs_are_never_copied(self, tmp_path: Path) -> None:
        source = self.make_repo(tmp_path / "src")
        copied = prepare_repo_source(source, tmp_path / "dst", version="1.11.0b2")

        assert (copied / "schemas" / "a.yml").exists()
        for venv in (".venv", ".venv-tc-1.10.6", ".venv-tc-1.11.0b2"):
            assert not (copied / venv).exists(), f"{venv} was copied into the tree served to Infrahub"

    def test_watch_is_stripped_for_an_older_target(self, tmp_path: Path) -> None:
        source = self.make_repo(tmp_path / "src")
        copied = prepare_repo_source(source, tmp_path / "dst", version="1.10.6")

        config = yaml.safe_load((copied / ".infrahub.yml").read_text(encoding="utf-8"))
        assert "watch" not in config["generator_definitions"][0]
        # The rest of the entry has to survive, or the definition stops working.
        assert config["generator_definitions"][0]["file_path"] == "./g.py"

    def test_watch_is_preserved_for_a_current_target(self, tmp_path: Path) -> None:
        source = self.make_repo(tmp_path / "src")
        copied = prepare_repo_source(source, tmp_path / "dst", version="1.11.0b2")

        config = yaml.safe_load((copied / ".infrahub.yml").read_text(encoding="utf-8"))
        assert config["generator_definitions"][0]["watch"] == {"files": ["src/infrahub_solution_ai_dc/"]}

    def test_adaptations_are_reported_for_the_manifest(self, tmp_path: Path) -> None:
        source = self.make_repo(tmp_path / "src")
        prepare_repo_source(source, tmp_path / "dst", version="1.10.6")

        assert any("watch" in note for note in describe_adaptations("1.10.6"))
        assert not list(describe_adaptations("1.11.0b2"))
