import os
from pathlib import Path
from time import sleep

import httpx
from invoke import Context, task

# If no version is indicated, we will take the latest
VERSION = os.getenv("VERSION", None)
CURRENT_DIRECTORY = Path(__file__).resolve()
MAIN_DIRECTORY_PATH = Path(__file__).parent
BASE_COMPOSE_FILE_URL = "https://infrahub.opsmill.io"


@task
def build(ctx: Context, cache: bool = True) -> None:
    """
    Build the docker image.
    """
    compose_cmd = "docker compose build"
    if not cache:
        compose_cmd += " --no-cache"
    with ctx.cd(MAIN_DIRECTORY_PATH):
        ctx.run(compose_cmd, pty=True)


@task
def start(ctx: Context) -> None:
    """
    Start the services using docker-compose in detached mode.
    """
    download_compose_file(ctx, override=False)
    ctx.run("docker compose up -d", pty=True)


@task
def destroy(ctx: Context) -> None:
    """
    Stop and remove containers, networks, and volumes.
    """
    download_compose_file(ctx, override=False)
    ctx.run("docker compose down -v", pty=True)


@task
def load(ctx: Context) -> None:
    load_schema(ctx)
    load_menu(ctx)
    sleep(5)
    ctx.run("infrahubctl object load objects/")
    ctx.run("infrahubctl object load repository.yml")


@task
def stop(ctx: Context) -> None:
    """
    Stop containers and remove networks.
    """
    download_compose_file(ctx, override=False)
    ctx.run("docker compose down", pty=True)


@task(help={"component": "Optional name of a specific service to restart."})
def restart(ctx: Context, component: str = "") -> None:
    """
    Restart all services or a specific one using docker-compose.
    """
    download_compose_file(ctx, override=False)
    if component:
        ctx.run(f"docker compose restart {component}", pty=True)
        return

    ctx.run("docker compose restart", pty=True)


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


@task
def test(ctx: Context) -> None:
    """
    Run tests using pytest.
    """
    ctx.run("pytest tests", pty=True)


@task(
    help={
        "version": "Infrahub version to run the integration suite against (e.g. 1.10.6, 1.11.0b1).",
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
            ctx.run("docker compose build", pty=True, env=env)
        # warn=True: a failing suite is a *result* of the comparison, not a reason to abort before
        # the timings are reported.
        ctx.run("pytest tests/integration -v", pty=True, env=env, warn=True)

    print(f"\nResults written to {results_path}")


@task(
    help={
        "baseline": "Baseline version (e.g. 1.10.6).",
        "candidate": "Candidate version (e.g. 1.11.0b1).",
        "output": "Where to write the markdown report.",
    }
)
def compare_versions(
    ctx: Context,
    baseline: str = "1.10.6",
    candidate: str = "1.11.0b1",
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


@task(help={"override": "Redownload the compose file even if it already exists."})
def download_compose_file(ctx: Context, version: str = "", override: bool = False) -> Path:  # noqa: ARG001
    """
    Download docker-compose.yml from InfraHub if missing or override is True.
    """
    compose_file = Path("./docker-compose.yml")

    compose_file_url = BASE_COMPOSE_FILE_URL

    if infrahub_version := version or VERSION:
        compose_file_url = f"{compose_file_url}/{infrahub_version}"

    if compose_file.exists() and not override:
        return compose_file

    response = httpx.get(compose_file_url)
    response.raise_for_status()

    compose_file.write_text(response.content.decode(), encoding="utf-8")

    return compose_file


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
    """Run Linter to check all Python files."""
    print(" - Check code with ruff")
    exec_cmd = "ruff check ."
    with ctx.cd(MAIN_DIRECTORY_PATH):
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
