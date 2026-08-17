"""Build the repository tree that the integration stack clones, adapted to the version under test.

Two problems are solved here, both of which otherwise force a hand-edited working tree before a
version comparison can run.

1. ``watch:`` does not exist before infrahub-sdk 1.23.0b0 (shipped with Infrahub 1.11), and
   ``InfrahubRepositoryConfig`` forbids extra keys -- so an older server rejects ``.infrahub.yml``
   outright and repository sync fails with "Extra inputs are not permitted". Rather than committing a
   branch with the entries removed (what the 1.10.6 baseline used to require), the key is stripped
   from the *copy* the stack clones whenever the target predates 1.11. ``INFRAHUB_BASE_VERSION``
   stays the single knob, and the working tree is never modified.

2. ``GitRepo`` copies its ``src_directory`` wholesale, ignoring only ``.git``. The repo root carries
   a ~370 MB ``.venv``, so every test class paid to copy it. ``porcelain.add`` honours ``.gitignore``
   and therefore never committed it (verified -- the committed tree holds tracked files only), so
   excluding it here changes what is *copied*, never what is *served*.

The exclusions and the rewrite apply identically to both versions under comparison, so neither
biases the timings.
"""

from __future__ import annotations

import shutil
from typing import TYPE_CHECKING, Any

import yaml
from packaging.version import InvalidVersion, Version

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

# The first release whose SDK accepts `watch:` in .infrahub.yml.
MIN_WATCH_VERSION = Version("1.11.0b0")

# Never committed by GitRepo (all are gitignored) and never read by the server, but all are copied
# byte for byte without this. `.venv` alone is ~370 MB.
EXCLUDED_FROM_COPY = (
    ".git",
    "node_modules",
    "__pycache__",
    ".mypy_cache",
    ".ruff_cache",
    ".pytest_cache",
    "perf-results",
)

# Any directory whose name starts with one of these is excluded as well. This is a prefix match, not
# an exact one, and that matters: a per-version comparison run creates sibling virtualenvs next to
# `.venv` (`.venv-tc-1.10.6`, `.venv-tc-1.11.0b1`), and an exact-match list silently keeps copying
# them. That is not a theoretical concern -- it filled the pytest temp root, which lives on a 16 GB
# **tmpfs**, so the copies consumed RAM until `copytree` died with "[Errno 122] Disk quota exceeded"
# and the host began failing to fork. Every integration test then errored out for a reason that looked
# nothing like its cause.
EXCLUDED_PREFIXES = (".venv",)


def supports_watch_key(version: str) -> bool:
    """Return whether ``version``'s SDK accepts ``watch:`` entries in .infrahub.yml.

    Unparseable versions (``local``, ``stable``, a branch build) are treated as current: those are
    always built from a recent tree, and guessing "old" would silently strip a key the server does
    support and quietly drop the src/ dependency closure from the run.
    """
    try:
        return Version(version) >= MIN_WATCH_VERSION
    except InvalidVersion:
        return True


def strip_watch_keys(node: Any) -> Any:  # noqa: ANN401 - walks arbitrary YAML
    """Recursively drop every ``watch`` key from a parsed .infrahub.yml document.

    Applied to the whole document rather than to the two sections that use it today
    (generator_definitions, python_transforms), so a `watch:` added to another section later is
    still handled instead of reintroducing the sync failure this exists to prevent.
    """
    if isinstance(node, dict):
        return {key: strip_watch_keys(value) for key, value in node.items() if key != "watch"}
    if isinstance(node, list):
        return [strip_watch_keys(item) for item in node]
    return node


def is_excluded(name: str) -> bool:
    """Whether a directory entry is kept out of the copy the stack clones."""
    return name in EXCLUDED_FROM_COPY or name.startswith(EXCLUDED_PREFIXES)


def _ignore(_directory: str, names: list[str]) -> set[str]:
    return {name for name in names if is_excluded(name)}


def prepare_repo_source(root_directory: Path, destination: Path, version: str) -> Path:
    """Copy the repo to ``destination``, rewriting .infrahub.yml for ``version``. Returns the copy.

    ``destination`` must not already exist -- ``copytree`` creates it.
    """
    shutil.copytree(src=root_directory, dst=destination, ignore=_ignore)

    if not supports_watch_key(version):
        config_path = destination / ".infrahub.yml"
        document = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        config_path.write_text(
            yaml.safe_dump(strip_watch_keys(document), sort_keys=False, default_flow_style=False),
            encoding="utf-8",
        )

    return destination


def describe_adaptations(version: str) -> Iterable[str]:
    """Yield a human-readable note per adaptation applied, for the run manifest."""
    if not supports_watch_key(version):
        yield f"stripped `watch:` from .infrahub.yml (unsupported before {MIN_WATCH_VERSION})"
