"""Tests for the pure parts of ``scripts/sandbox_setup.py``, the entry point of the public sandbox pipeline."""

import importlib.util
from pathlib import Path
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "sandbox_setup.py"

_spec = importlib.util.spec_from_file_location("sandbox_setup", SCRIPT)
assert _spec is not None
assert _spec.loader is not None
setup = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(setup)

ENVIRONMENT = {
    "INFRAHUB_ADDRESS": "https://infrahub-scratch-ai-dc.infrahub.online",
    "INFRAHUB_API_TOKEN": "token-value",
    "INFRAHUB_REPO_URL": "https://github.com/opsmill/infrahub-solution-ai-dc",
    "INFRAHUB_REPO_REF": "main",
}


def node(sync: str, operational: str = "ok") -> dict[str, Any]:
    return {"name": {"value": "r"}, "sync_status": {"value": sync}, "operational_status": {"value": operational}}


def test_variables_are_read() -> None:
    assert setup.read_variables(ENVIRONMENT) == ENVIRONMENT


@pytest.mark.parametrize("name", sorted(ENVIRONMENT))
def test_a_missing_or_blank_variable_is_named(name: str) -> None:
    for broken in ({k: v for k, v in ENVIRONMENT.items() if k != name}, {**ENVIRONMENT, name: "  "}):
        with pytest.raises(setup.SetupError, match=name):
            setup.read_variables(broken)


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://github.com/opsmill/infrahub-solution-ai-dc", "infrahub-solution-ai-dc"),
        ("https://github.com/opsmill/infrahub-solution-ai-dc/", "infrahub-solution-ai-dc"),
        ("https://github.com/opsmill/infrahub-solution-ai-dc.git", "infrahub-solution-ai-dc"),
        ("/upstream", "upstream"),
    ],
)
def test_repository_name_is_the_last_part_of_the_address(url: str, expected: str) -> None:
    assert setup.repository_name(url) == expected


def test_a_repository_address_without_a_name_is_refused() -> None:
    with pytest.raises(setup.SetupError):
        setup.repository_name("/")


def test_import_state() -> None:
    assert setup.import_state([]) == "waiting"
    assert setup.import_state([node("in-sync")]) == "in-sync"
    assert setup.import_state([node("in-sync"), node("syncing")]) == "waiting"
    with pytest.raises(setup.SetupError, match="error-import"):
        setup.import_state([node("error-import")])
    with pytest.raises(setup.SetupError, match="credentials"):
        setup.import_state([node("in-sync", "error-cred")])
