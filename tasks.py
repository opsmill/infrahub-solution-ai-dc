import os
from pathlib import Path
from time import sleep

import httpx
from invoke import Context, task

# If no version is indicated, we will take the latest
VERSION = os.getenv("INFRAHUB_IMAGE_VER", None)
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


@task(help={"override": "Redownload the compose file even if it already exists."})
def download_compose_file(ctx: Context, infrahub_version: str = "", override: bool = False) -> Path:  # noqa: ARG001
    """
    Download docker-compose.yml from InfraHub if missing or override is True.
    """
    compose_file = Path("./docker-compose.yml")

    compose_file_url = BASE_COMPOSE_FILE_URL

    if infrahub_version:
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
