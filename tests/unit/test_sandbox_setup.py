"""Tests for ``scripts/sandbox_setup.py``, the entry point of the public sandbox pipeline. They need no Infrahub."""

import asyncio
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


def test_unknown_state_waits_and_a_connection_error_is_unreadable() -> None:
    assert setup.import_state([node("unknown")]) == "waiting"
    assert setup.import_state([node("unknown", "error-connection")]) == "unreadable"
    assert setup.import_state([node("unknown", "error")]) == "unreadable"
    assert setup.import_state([node("in-sync", "error")]) == "in-sync"


def test_required_generators_are_the_ones_the_trigger_rules_run() -> None:
    assert setup.required_generators() == {
        "generate-fabric",
        "generate-pod",
        "generate-rack",
        "generate-server",
        "generate-tenant",
    }


class FakeClient:
    """Answer ``execute_graphql`` with scripted repository nodes and generator definition names, then repeat the last one."""

    def __init__(self, *answers: tuple[list[dict[str, Any]], list[str]]) -> None:
        self.answers = list(answers)
        self.calls = 0

    async def execute_graphql(self, _query: str) -> dict[str, Any]:
        nodes, generators = self.answers[min(self.calls, len(self.answers) - 1)]
        self.calls += 1
        return {
            "CoreGenericRepository": {"edges": [{"node": n} for n in nodes]},
            "CoreGeneratorDefinition": {"edges": [{"node": {"name": {"value": g}}} for g in generators]},
        }


async def test_wait_returns_when_in_sync_and_the_generators_exist() -> None:
    client = FakeClient(([], []), ([node("syncing")], []), ([node("in-sync")], ["g"]))

    await setup.wait_for_import(client, seconds=30, interval=0, generators={"g"})

    assert client.calls == 3


async def test_wait_does_not_return_while_a_generator_definition_is_missing() -> None:
    client = FakeClient(([node("in-sync")], ["a"]))

    with pytest.raises(setup.SetupError, match=r"Missing generator definitions: \['b'\]"):
        await setup.wait_for_import(client, seconds=0, interval=0, generators={"a", "b"})


async def test_wait_stops_on_an_unreadable_repository_after_three_polls() -> None:
    client = FakeClient(([node("unknown", "error-connection")], []))

    with pytest.raises(setup.SetupError, match="cannot read the repository"):
        await setup.wait_for_import(client, seconds=30, interval=0, generators=set())

    assert client.calls == setup.UNREADABLE_POLLS


async def test_wait_survives_one_failed_pull() -> None:
    client = FakeClient(([node("unknown", "error-connection")], []), ([node("in-sync")], []))

    await setup.wait_for_import(client, seconds=30, interval=0, generators=set())

    assert client.calls == 2


def test_main_exits_with_one_on_a_setup_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    async def fail() -> None:
        await asyncio.sleep(0)
        message = "no way"
        raise setup.SetupError(message)

    monkeypatch.setattr(setup, "run", fail)

    assert setup.main() == 1
    assert "sandbox-setup failed: no way" in capsys.readouterr().err


def test_main_exits_with_zero_when_the_setup_works(monkeypatch: pytest.MonkeyPatch) -> None:
    async def done() -> None:
        await asyncio.sleep(0)

    monkeypatch.setattr(setup, "run", done)

    assert setup.main() == 0
