import os
from pathlib import Path
from time import sleep

import httpx
from invoke import Context, Exit, task

try:
    from infrahub_testcontainers import __version__ as _testcontainers_version
except ImportError:  # pragma: no cover
    _testcontainers_version = ""

# If no version is indicated, we will take the latest
VERSION = os.getenv("VERSION", None)
CURRENT_DIRECTORY = Path(__file__).resolve()
MAIN_DIRECTORY_PATH = Path(__file__).parent
BASE_COMPOSE_FILE_URL = "https://infrahub.opsmill.io"
COMPOSE_FILE = MAIN_DIRECTORY_PATH / "docker-compose.yml"
DOCUMENTATION_DIRECTORY = MAIN_DIRECTORY_PATH / "docs"

COMMUNITY = "community"
ENTERPRISE = "enterprise"

# Community and Enterprise ship separate compose stacks built on separate images. INFRAHUB_EDITION is
# the only knob a user sets; the compose URL, the base image the Dockerfile extends, and the image
# this project builds are all derived from it here so they cannot drift apart.
EDITIONS = {
    COMMUNITY: {
        "compose_path": "",
        "base_image": "registry.opsmill.io/opsmill/infrahub",
        "solution_image": "opsmill/infrahub-solution-ai-dc",
        "image_user": "root",
    },
    ENTERPRISE: {
        "compose_path": "/enterprise",
        "base_image": "registry.opsmill.io/opsmill/infrahub-enterprise",
        "solution_image": "opsmill/infrahub-enterprise-solution-ai-dc",
        "image_user": "infrahub",
    },
}


def _derived_base_version() -> str:
    """Return the Infrahub version to build and run against, from the installed testcontainers."""
    if not _testcontainers_version:
        msg = "infrahub-testcontainers is not installed; run `uv sync` before using the docker tasks"
        raise RuntimeError(msg)
    return _testcontainers_version


def resolve_edition(edition: str = "") -> str:
    """Return the Infrahub edition to operate on, from an explicit value or INFRAHUB_EDITION."""
    resolved = edition or os.getenv("INFRAHUB_EDITION") or COMMUNITY
    if resolved not in EDITIONS:
        expected = ", ".join(EDITIONS)
        message = f"Unknown Infrahub edition {resolved!r}, expected one of: {expected}"
        raise Exit(message, code=1)
    return resolved


def compose_env(edition: str) -> dict[str, str]:
    """Return the image variables docker-compose.override.yml and the Dockerfile read for an edition.

    The version is one of them, and is passed explicitly rather than left in the ambient environment:
    both the compose override and the Dockerfile fail hard without it, so it belongs with the other
    image variables where it can be seen. An explicit ``INFRAHUB_BASE_VERSION`` still wins, which is
    how CI pins a build to a version other than the installed one.
    """
    return {
        "INFRAHUB_BASE_IMAGE": EDITIONS[edition]["base_image"],
        "INFRAHUB_SOLUTION_IMAGE": EDITIONS[edition]["solution_image"],
        "INFRAHUB_IMAGE_USER": EDITIONS[edition]["image_user"],
        "INFRAHUB_BASE_VERSION": os.environ.get("INFRAHUB_BASE_VERSION") or _derived_base_version(),
    }


def compose_file_edition(compose_file: Path) -> str:
    """Return the edition a downloaded compose file belongs to, identified by the image it references."""
    content = compose_file.read_text(encoding="utf-8")
    return ENTERPRISE if EDITIONS[ENTERPRISE]["base_image"] in content else COMMUNITY


def require_matching_compose_file(compose_file: Path, edition: str) -> None:
    """Refuse to drive the stack with a compose file from the other edition."""
    found = compose_file_edition(compose_file)
    if found == edition:
        return

    message = (
        f"{compose_file.name} is the {found} compose file but the edition is {edition}. "
        f"Run `inv download-compose-file --override --edition={edition}` to fetch the {edition} one."
    )
    raise Exit(message, code=1)


def prepare_compose(ctx: Context, edition: str) -> dict[str, str]:
    """Make sure the compose file on disk matches the edition, and return that edition's image variables."""
    compose_file = download_compose_file(ctx, edition=edition, override=False)
    require_matching_compose_file(compose_file, edition)
    return compose_env(edition)


@task(help={"edition": "Infrahub edition to build, community or enterprise. Defaults to INFRAHUB_EDITION."})
def build(ctx: Context, cache: bool = True, edition: str = "") -> None:
    """
    Build the docker image.
    """
    resolved = resolve_edition(edition)
    compose_cmd = "docker compose build"
    if not cache:
        compose_cmd += " --no-cache"
    with ctx.cd(MAIN_DIRECTORY_PATH):
        ctx.run(compose_cmd, pty=True, env=prepare_compose(ctx, resolved))


@task(help={"edition": "Infrahub edition to start, community or enterprise. Defaults to INFRAHUB_EDITION."})
def start(ctx: Context, edition: str = "") -> None:
    """
    Start the services using docker-compose in detached mode.
    """
    resolved = resolve_edition(edition)
    ctx.run("docker compose up -d", pty=True, env=prepare_compose(ctx, resolved))


@task(help={"edition": "Infrahub edition to destroy, community or enterprise. Defaults to INFRAHUB_EDITION."})
def destroy(ctx: Context, edition: str = "") -> None:
    """
    Stop and remove containers, networks, and volumes.
    """
    resolved = resolve_edition(edition)
    ctx.run("docker compose down -v", pty=True, env=prepare_compose(ctx, resolved))


@task
def load(ctx: Context) -> None:
    load_schema(ctx)
    load_menu(ctx)
    sleep(5)
    ctx.run("infrahubctl object load objects/")
    ctx.run("infrahubctl object load repository.yml")


@task(help={"edition": "Infrahub edition to stop, community or enterprise. Defaults to INFRAHUB_EDITION."})
def stop(ctx: Context, edition: str = "") -> None:
    """
    Stop containers and remove networks.
    """
    resolved = resolve_edition(edition)
    ctx.run("docker compose down", pty=True, env=prepare_compose(ctx, resolved))


@task(
    help={
        "component": "Optional name of a specific service to restart.",
        "edition": "Infrahub edition to restart, community or enterprise. Defaults to INFRAHUB_EDITION.",
    }
)
def restart(ctx: Context, component: str = "", edition: str = "") -> None:
    """
    Restart all services or a specific one using docker-compose.
    """
    resolved = resolve_edition(edition)
    env = prepare_compose(ctx, resolved)
    if component:
        ctx.run(f"docker compose restart {component}", pty=True, env=env)
        return

    ctx.run("docker compose restart", pty=True, env=env)


@task
def load_menu(ctx: Context) -> None:
    """
    Load schemas into InfraHub using infrahubctl.
    """
    ctx.run("infrahubctl menu load menus/", pty=True)


@task
def load_schema(ctx: Context) -> None:
    """
    Load schemas into InfraHub using infrahubctl.
    """
    ctx.run("infrahubctl schema load schemas", pty=True)


@task(name="test-unit")
def test_unit(ctx: Context) -> None:
    """Run every test that needs no Infrahub deployment."""
    for cmd in ("pytest tests/unit", "pytest tests/integration -m offline"):
        ctx.run(cmd, pty=True)


@task(
    name="test-integration",
    help={"tier": "core (default) runs everything but the extended tier; full runs all of it."},
)
def test_integration(ctx: Context, tier: str = "core") -> None:
    """Run the integration suite against a throwaway Infrahub deployment."""
    if tier not in {"core", "full"}:
        message = f"tier must be 'core' or 'full', got {tier!r}"
        raise Exit(message)
    marker = "" if tier == "full" else ' -m "not extended"'
    ctx.run(f"pytest tests/integration{marker}", pty=True)


@task
def test(ctx: Context) -> None:
    """
    Run tests using pytest.
    """
    ctx.run("pytest tests", pty=True)


@task(
    help={
        "version": "Infrahub version to run the integration suite against (e.g. 1.10.6, 1.11.0).",
        "output": "Where to write the timing JSON (default: perf-results/<version>.json).",
        "build_image": "Build the project image for that version first (default: yes).",
    }
)
def test_version(ctx: Context, version: str, output: str = "", build_image: bool = True) -> None:
    """Run the integration suite against one Infrahub version, capturing timings.

    INFRAHUB_BASE_VERSION is the only knob: the repo copy the stack clones is adapted automatically
    for releases that predate a feature it uses (see tests/integration/repo_source.py), so no file in
    the working tree needs editing to test an older release.
    """
    results_path = output or f"perf-results/{version}.json"
    env = {"INFRAHUB_BASE_VERSION": version, "AI_DC_PERF_OUT": results_path}

    with ctx.cd(MAIN_DIRECTORY_PATH):
        if build_image:
            # Through prepare_compose so the compose file on disk is present and matches the edition;
            # the version in ``env`` is merged last, so it wins over the installed-package default.
            ctx.run("docker compose build", pty=True, env={**prepare_compose(ctx, resolve_edition()), **env})
        # warn=True: a failing suite is a *result* of the comparison, not a reason to abort before
        # the timings are reported.
        ctx.run("pytest tests/integration -v", pty=True, env=env, warn=True)

    print(f"\nResults written to {results_path}")


@task(name="docs")
def docs_build(ctx: Context) -> None:
    """Build the documentation website."""
    with ctx.cd(DOCUMENTATION_DIRECTORY):
        ctx.run("pnpm run build", pty=True)


@task(
    help={
        "baseline": "Baseline version (e.g. 1.10.6).",
        "candidate": "Candidate version (e.g. 1.11.0).",
        "output": "Where to write the markdown report.",
    }
)
def compare_versions(
    ctx: Context,
    baseline: str = "1.10.6",
    candidate: str = "1.11.0",
    output: str = "perf-results/comparison.md",
) -> None:
    """Run the integration suite against two full Infrahub stacks and diff the results.

    Delegates to dev/compare_versions.sh, which moves *both* halves of each stack together -- the
    application image and the infrahub-testcontainers package that defines the surrounding compose
    (Neo4j/RabbitMQ/Redis pins, container ulimits). `inv test-version` swaps the application image
    only, which is faster but blind to stack-level changes between releases.
    """
    with ctx.cd(MAIN_DIRECTORY_PATH):
        ctx.run(f"./dev/compare_versions.sh {baseline} {candidate} {output}", pty=True)


@task(
    help={
        "override": "Redownload the compose file even if it already exists.",
        "edition": "Infrahub edition to download, community or enterprise. Defaults to INFRAHUB_EDITION.",
    }
)
def download_compose_file(ctx: Context, version: str = "", override: bool = False, edition: str = "") -> Path:  # noqa: ARG001
    """
    Download docker-compose.yml from InfraHub if missing or override is True.
    """
    resolved = resolve_edition(edition)

    if COMPOSE_FILE.exists() and not override:
        return COMPOSE_FILE

    compose_file_url = f"{BASE_COMPOSE_FILE_URL}{EDITIONS[resolved]['compose_path']}"

    if infrahub_version := version or VERSION:
        compose_file_url = f"{compose_file_url}/{infrahub_version}"

    print(f" - Downloading the {resolved} compose file from {compose_file_url}")
    response = httpx.get(compose_file_url)
    response.raise_for_status()

    COMPOSE_FILE.write_text(response.content.decode(), encoding="utf-8")

    return COMPOSE_FILE


@task(name="format")
def format_python(ctx: Context) -> None:
    """Run RUFF to format all Python files."""

    exec_cmds = ["ruff format .", "ruff check . --fix"]
    with ctx.cd(MAIN_DIRECTORY_PATH):
        for cmd in exec_cmds:
            ctx.run(cmd, pty=True)


@task
def lint_yaml(ctx: Context) -> None:
    """Run Linter to check all Python files."""
    print(" - Check code with yamllint")
    exec_cmd = "yamllint ."
    with ctx.cd(MAIN_DIRECTORY_PATH):
        ctx.run(exec_cmd, pty=True)


@task
def lint_mypy(ctx: Context) -> None:
    """Run Linter to check all Python files."""
    print(" - Check code with mypy")
    exec_cmd = "mypy --show-error-codes ."
    with ctx.cd(MAIN_DIRECTORY_PATH):
        ctx.run(exec_cmd, pty=True)


@task
def lint_ruff(ctx: Context) -> None:
    """Run Linter to check all Python files; both invocations, since ``ruff check`` skips formatting."""
    print(" - Check code with ruff")
    exec_cmds = ["ruff format --check --diff .", "ruff check ."]
    with ctx.cd(MAIN_DIRECTORY_PATH):
        for exec_cmd in exec_cmds:
            ctx.run(exec_cmd, pty=True)


@task
def lint_markdown(ctx: Context) -> None:
    """Run rumdl to check all Markdown files."""
    print(" - Check code with rumdl")
    exec_cmd = "rumdl check ."
    with ctx.cd(MAIN_DIRECTORY_PATH):
        ctx.run(exec_cmd, pty=True)


@task(name="lint")
def lint_all(ctx: Context) -> None:
    """Run all linters."""
    lint_markdown(ctx)
    lint_yaml(ctx)
    lint_ruff(ctx)
    lint_mypy(ctx)
