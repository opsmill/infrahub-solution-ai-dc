"""Unit coverage for the ``watch.files`` entries in ``.infrahub.yml``.

Infrahub only re-runs a Python definition when a file inside its dependency closure changes. That
closure is the directory holding ``file_path``, so a module under ``src/`` reaches it only through a
``watch`` entry. Two properties are pinned here, and both broke once (issue #119):

1. Every entry names a file that exists. A stale entry only logs a warning on repository import.
2. Every shared module a definition imports, directly or through another shared module, is watched.
   When ``generator.py`` became ``checksum.py`` the entries kept the old name, so a change to
   ``checksum.py`` stopped re-running the four generators that import it.
"""

from __future__ import annotations

import ast
import operator
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE = "infrahub_solution_ai_dc"
PACKAGE_DIR = REPO_ROOT / "src" / PACKAGE

CONFIG = yaml.safe_load((REPO_ROOT / ".infrahub.yml").read_text(encoding="utf-8"))
DEFINITIONS = [
    definition
    for section in ("generator_definitions", "python_transforms")
    for definition in CONFIG.get(section, [])
    if "watch" in definition
]


def _imported_package_modules(path: Path) -> set[Path]:
    """Return the shared-package modules ``path`` imports, absolute or relative, at any level."""
    in_package = path.parent == PACKAGE_DIR
    found: set[Path] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if not isinstance(node, ast.ImportFrom):
            continue
        if node.level == 0 and node.module and node.module.split(".")[0] == PACKAGE:
            parts = node.module.split(".")[1:]
        elif node.level == 1 and in_package:
            parts = node.module.split(".") if node.module else []
        else:
            continue
        # `from pkg import sorting` names a module; `from pkg.checksum import Checksum` names a symbol.
        candidates = [parts] if parts else [[alias.name] for alias in node.names]
        for candidate in candidates:
            module = PACKAGE_DIR.joinpath(*candidate).with_suffix(".py")
            if module.is_file():
                found.add(module)
    return found


def _package_closure(path: Path) -> set[Path]:
    pending = _imported_package_modules(path)
    closure: set[Path] = set()
    while pending:
        module = pending.pop()
        if module not in closure:
            closure.add(module)
            pending |= _imported_package_modules(module)
    return closure


def _watched(definition: dict) -> set[Path]:
    return {(REPO_ROOT / entry).resolve() for entry in definition["watch"]["files"]}


@pytest.mark.parametrize("definition", DEFINITIONS, ids=operator.itemgetter("name"))
class TestWatchFiles:
    def test_every_entry_names_an_existing_file(self, definition: dict) -> None:
        missing = [entry for entry in definition["watch"]["files"] if not (REPO_ROOT / entry).is_file()]
        assert not missing

    def test_every_imported_shared_module_is_watched(self, definition: dict) -> None:
        imported = _package_closure((REPO_ROOT / definition["file_path"]).resolve())
        unwatched = sorted(str(module.relative_to(REPO_ROOT)) for module in imported - _watched(definition))
        assert not unwatched
