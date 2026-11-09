"""Build the demo on an Infrahub that already runs: the work behind ``invoke sandbox-setup``.

The public sandbox pipeline deploys an empty Infrahub, then runs the task with four variables:

- ``INFRAHUB_ADDRESS`` and ``INFRAHUB_API_TOKEN``: the Infrahub to build the demo on
- ``INFRAHUB_REPO_URL`` and ``INFRAHUB_REPO_REF``: the repository to register

The steps are idempotent, so running them again gives the same result:

1. Register the repository as a read-only repository. Infrahub then imports the schemas, the menu, the objects, the
   generators, the transforms and the artifact definitions from ``.infrahub.yml``.
2. Wait until the import is ``in-sync``. The trigger rules name generator definitions, which exist only after the import.
3. Load ``triggers.yml``, the rules that make one run of ``generate-fabric`` cascade to the pods and the racks.

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

from infrahub_sdk import Config, InfrahubClient

ROOT = Path(__file__).resolve().parent.parent
TRIGGERS_FILE = "triggers.yml"
REQUIRED_VARIABLES = ("INFRAHUB_ADDRESS", "INFRAHUB_API_TOKEN", "INFRAHUB_REPO_URL", "INFRAHUB_REPO_REF")
# The pipeline stops the task after SETUP_TIMEOUT (1800 s by default). This wait stays well inside it.
IMPORT_TIMEOUT = int(os.getenv("SANDBOX_SETUP_IMPORT_TIMEOUT", "900"))
POLL_INTERVAL = int(os.getenv("SANDBOX_SETUP_POLL_INTERVAL", "5"))

REPOSITORY_STATUS_QUERY = """
{
  CoreGenericRepository {
    edges { node { name { value } sync_status { value } operational_status { value } } }
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


def import_state(nodes: list[dict[str, Any]]) -> str:
    """Return ``in-sync``, ``waiting`` or raise ``SetupError`` when a repository failed or has no usable credential."""
    if not nodes:
        return "waiting"
    states = [node["sync_status"]["value"] for node in nodes]
    if any(state.startswith("error") for state in states):
        message = f"The repository import failed: {states}. See the Infrahub task list for the error."
        raise SetupError(message)
    if any(node["operational_status"]["value"] == "error-cred" for node in nodes):
        message = "Infrahub cannot read the repository: its credentials were refused."
        raise SetupError(message)
    return "in-sync" if all(state == "in-sync" for state in states) else "waiting"


async def register_repository(client: InfrahubClient, url: str, ref: str) -> None:
    """Create the read-only repository, or update it when it exists."""
    repository = await client.create(kind="CoreReadOnlyRepository", name=repository_name(url), location=url, ref=ref)
    await repository.save(allow_upsert=True)


async def wait_for_import(client: InfrahubClient, seconds: int = IMPORT_TIMEOUT, interval: int = POLL_INTERVAL) -> None:
    """Wait until every repository is ``in-sync``."""
    deadline = time.monotonic() + seconds
    while True:
        result = await client.execute_graphql(REPOSITORY_STATUS_QUERY)
        nodes = [edge["node"] for edge in result["CoreGenericRepository"]["edges"]]
        if import_state(nodes) == "in-sync":
            return
        if time.monotonic() >= deadline:
            message = f"The repository is still not in sync after {seconds} seconds."
            raise SetupError(message)
        await asyncio.sleep(interval)


def load_trigger_rules() -> None:
    """Load ``triggers.yml`` on the default branch with ``infrahubctl``, which reads the same two variables."""
    result = subprocess.run(  # noqa: S603
        ["infrahubctl", "object", "load", TRIGGERS_FILE],  # noqa: S607
        cwd=ROOT,
        check=False,
    )
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
