"""Build the demo on an Infrahub that already runs: the work behind ``invoke sandbox-setup``.

The public sandbox pipeline deploys an empty Infrahub, then runs the task with four variables:

- ``INFRAHUB_ADDRESS`` and ``INFRAHUB_API_TOKEN``: the Infrahub to build the demo on
- ``INFRAHUB_REPO_URL`` and ``INFRAHUB_REPO_REF``: the repository to register

The steps are idempotent, so running them again gives the same result:

1. Register the repository as a read-only repository. Infrahub then imports the schemas, the menu, the objects, the
   generators, the transforms and the artifact definitions from ``.infrahub.yml``.
2. Wait until the import is ``in-sync`` and the generator definitions that ``triggers.yml`` names exist.
3. Load ``triggers.yml``, the rules that make a run of ``generate-fabric`` on a branch cascade to the pods and the racks.
   The rules apply on branches only, so a run on ``main`` builds the fabric tier alone.

A repeat run with another ref can see the previous import as ``in-sync`` until Infrahub starts the new one. The wait then
returns at once, and the pipeline's own wait after the task covers the new import.

The task starts no container and calls no ``localhost`` address.
"""

# ruff: noqa: INP001

from __future__ import annotations

import asyncio
import os
import subprocess  # noqa: S404
import sys
import time
from pathlib import Path
from typing import Any

import yaml
from infrahub_sdk import Config, InfrahubClient

ROOT = Path(__file__).resolve().parent.parent
TRIGGERS_FILE = "triggers.yml"
REQUIRED_VARIABLES = ("INFRAHUB_ADDRESS", "INFRAHUB_API_TOKEN", "INFRAHUB_REPO_URL", "INFRAHUB_REPO_REF")
# The pipeline stops the task after SETUP_TIMEOUT (1800 s by default). This wait stays well inside it.
IMPORT_TIMEOUT = int(os.getenv("SANDBOX_SETUP_IMPORT_TIMEOUT", "900"))
POLL_INTERVAL = int(os.getenv("SANDBOX_SETUP_POLL_INTERVAL", "5"))
# infrahubctl loads a few dozen small nodes; this only stops a hung call.
TRIGGERS_TIMEOUT = 600
# An unreadable repository (wrong address or ref, no network) may recover on the next pull, so it must last this many polls.
UNREADABLE_POLLS = 3

STATUS_QUERY = """
{
  CoreGenericRepository {
    edges { node { name { value } sync_status { value } operational_status { value } } }
  }
  CoreGeneratorDefinition {
    edges { node { name { value } } }
  }
}
"""


class SetupError(Exception):
    """The setup cannot continue; the message says why."""


def read_variables(environ: dict[str, str] | None = None) -> dict[str, str]:
    """Return the four variables the pipeline sets, or raise ``SetupError`` naming the ones that are missing or empty."""
    source = os.environ if environ is None else environ
    missing = [name for name in REQUIRED_VARIABLES if not source.get(name, "").strip()]
    if missing:
        message = f"Set {', '.join(missing)}: the pipeline passes them to the sandbox-setup task."
        raise SetupError(message)
    return {name: source[name] for name in REQUIRED_VARIABLES}


def repository_name(url: str) -> str:
    """Name the repository like the pipeline does for a demo without the task: the last part of its address."""
    name = url.rstrip("/").rsplit("/", maxsplit=1)[-1].removesuffix(".git")
    if not name:
        message = f"Cannot name the repository from INFRAHUB_REPO_URL {url!r}."
        raise SetupError(message)
    return name


def required_generators(path: Path = ROOT / TRIGGERS_FILE) -> set[str]:
    """Return the names of the generator definitions that the trigger rules of ``triggers.yml`` run."""
    names: set[str] = set()
    for document in yaml.safe_load_all(path.read_text(encoding="utf-8")):
        spec = document.get("spec", {}) if isinstance(document, dict) else {}
        if spec.get("kind") == "CoreGeneratorAction":
            names.update(item["generator"] for item in spec["data"] if "generator" in item)
    return names


def import_state(nodes: list[dict[str, Any]]) -> str:
    """Return ``in-sync``, ``unreadable`` or ``waiting``; raise ``SetupError`` when the import failed or the credential is refused."""
    if not nodes:
        return "waiting"
    states = [node["sync_status"]["value"] for node in nodes]
    if any(state.startswith("error") for state in states):
        message = f"The repository import failed: {states}. See the Infrahub task list for the error."
        raise SetupError(message)
    if any(node["operational_status"]["value"] == "error-cred" for node in nodes):
        message = "Infrahub cannot read the repository: its credentials were refused."
        raise SetupError(message)
    if all(state == "in-sync" for state in states):
        return "in-sync"
    unreadable = {"error-connection", "error"}
    if any(node["operational_status"]["value"] in unreadable for node in nodes):
        return "unreadable"
    return "waiting"


async def register_repository(client: InfrahubClient, url: str, ref: str) -> None:
    """Create the read-only repository, or update it when it exists."""
    repository = await client.create(kind="CoreReadOnlyRepository", name=repository_name(url), location=url, ref=ref)
    await repository.save(allow_upsert=True)


async def wait_for_import(
    client: InfrahubClient,
    seconds: int = IMPORT_TIMEOUT,
    interval: int = POLL_INTERVAL,
    generators: set[str] | None = None,
) -> None:
    """Wait until every repository is ``in-sync`` and the generator definitions that the trigger rules name exist."""
    needed = required_generators() if generators is None else generators
    deadline = time.monotonic() + seconds
    unreadable = 0
    missing = needed
    while True:
        result = await client.execute_graphql(STATUS_QUERY)
        nodes = [edge["node"] for edge in result["CoreGenericRepository"]["edges"]]
        present = {edge["node"]["name"]["value"] for edge in result["CoreGeneratorDefinition"]["edges"]}
        missing = needed - present
        state = import_state(nodes)
        unreadable = unreadable + 1 if state == "unreadable" else 0
        if unreadable >= UNREADABLE_POLLS:
            statuses = [node["operational_status"]["value"] for node in nodes]
            message = f"Infrahub cannot read the repository (operational status {statuses}): check its address and ref."
            raise SetupError(message)
        if state == "in-sync" and not missing:
            return
        if time.monotonic() >= deadline:
            detail = f" Missing generator definitions: {sorted(missing)}." if missing else ""
            message = f"The repository is still not in sync after {seconds} seconds.{detail}"
            raise SetupError(message)
        await asyncio.sleep(interval)


def load_trigger_rules() -> None:
    """Load ``triggers.yml`` on the default branch with ``infrahubctl``, which reads the same two variables."""
    try:
        result = subprocess.run(  # noqa: S603
            ["infrahubctl", "object", "load", TRIGGERS_FILE],  # noqa: S607
            cwd=ROOT,
            check=False,
            timeout=TRIGGERS_TIMEOUT,
        )
    except FileNotFoundError as error:
        message = "infrahubctl is not on PATH: run the task with `uv run invoke sandbox-setup`."
        raise SetupError(message) from error
    except subprocess.TimeoutExpired as error:
        message = f"infrahubctl did not load {TRIGGERS_FILE} within {TRIGGERS_TIMEOUT} seconds."
        raise SetupError(message) from error
    if result.returncode != 0:
        message = f"infrahubctl could not load {TRIGGERS_FILE} (exit code {result.returncode})."
        raise SetupError(message)


async def run() -> None:
    """Run the three steps."""
    variables = read_variables()
    client = InfrahubClient(
        address=variables["INFRAHUB_ADDRESS"],
        config=Config(api_token=variables["INFRAHUB_API_TOKEN"], retry_on_failure=True, max_retry_duration=300),
    )
    sys.stdout.write(f"Registering {variables['INFRAHUB_REPO_URL']} at {variables['INFRAHUB_REPO_REF']}...\n")
    await register_repository(client, variables["INFRAHUB_REPO_URL"], variables["INFRAHUB_REPO_REF"])
    sys.stdout.write("Waiting for the repository import to finish...\n")
    await wait_for_import(client)
    sys.stdout.write(f"Loading {TRIGGERS_FILE}...\n")
    load_trigger_rules()
    sys.stdout.write("Sandbox setup done.\n")


def main() -> int:
    """Run the setup and return the exit code: nonzero on any failure."""
    try:
        asyncio.run(run())
    except SetupError as error:
        sys.stderr.write(f"sandbox-setup failed: {error}\n")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
