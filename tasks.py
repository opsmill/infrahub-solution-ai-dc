import os
from pathlib import Path
from shlex import quote
from time import monotonic, sleep

import httpx
from infrahub_sdk import InfrahubClientSync
from infrahub_sdk.protocols import CoreRepositorySync
from invoke import Context, Exit, task

# If no version is indicated, we will take the latest
VERSION = os.getenv("VERSION", None)
CURRENT_DIRECTORY = Path(__file__).resolve()
MAIN_DIRECTORY_PATH = Path(__file__).parent
BASE_COMPOSE_FILE_URL = "https://infrahub.opsmill.io"
# Bare mirror of the local checkout, living inside the directory bind-mounted at /upstream.
UPSTREAM_BARE_REPO = MAIN_DIRECTORY_PATH / ".upstream.git"
# Branch the containers track in that mirror. Infrahub imports the remote branch whose name
# matches its own, so this has to stay `main` — and match `default_branch` in repository.yml.
UPSTREAM_DEFAULT_BRANCH = "main"
# Must match the CoreRepository name in repository.yml.
REPOSITORY_NAME = "test-repository"


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
def publish_upstream(ctx: Context) -> None:
    """
    Mirror the current checkout into a bare repo the containers can clone.

    The checkout is bind-mounted at /upstream, but the git agent cannot clone it
    directly when it is a git worktree: `.git` is then a file pointing at a path
    outside the mount. A bare repo inside the mount clones cleanly either way.

    Every local branch is copied over, then the current checkout is force-pushed
    over the mirror's `main` — whatever the branch is called on the host. Infrahub
    tracks the remote branch named after its own (`main`), so this is what makes it
    follow your checkout; the other branches stay available to the containers.

    Incremental and safe to re-run after every commit: `git init --bare` is a no-op
    on an existing mirror, so branches the git agent pushed back into it survive.
    """
    bare = quote(str(UPSTREAM_BARE_REPO))
    ctx.run(f"git init --bare {bare}", pty=True)
    # Best-effort and deliberately not forced: a mirror branch the git agent has moved on
    # is rejected rather than clobbered, and one stale copy must not fail the whole publish.
    ctx.run(f"git push {bare} 'refs/heads/*:refs/heads/*'", pty=True, warn=True)
    # The checkout, however, is authoritative for the branch Infrahub tracks.
    ctx.run(f"git push --force {bare} HEAD:refs/heads/{UPSTREAM_DEFAULT_BRANCH}", pty=True)
    # `git init --bare` only honours the initial branch on a fresh repo; set it either way.
    ctx.run(f"git -C {bare} symbolic-ref HEAD refs/heads/{UPSTREAM_DEFAULT_BRANCH}", pty=True)


@task
def wait_for_repository(ctx: Context, timeout: int = 300) -> None:
    """
    Block until Infrahub has imported the commit currently published upstream.
    """
    rev_parse = ctx.run("git rev-parse HEAD", hide=True)
    if not rev_parse:
        message = "Unable to resolve the current commit"
        raise Exit(message)

    head = rev_parse.stdout.strip()
    client = InfrahubClientSync()
    deadline = monotonic() + timeout
    status = "unknown"
    while True:
        repo = client.get(kind=CoreRepositorySync, name__value=REPOSITORY_NAME, raise_when_missing=False)
        if repo:
            status = repo.sync_status.value
            # `error-import` alone is not fatal: it may still describe the previous commit,
            # and the periodic fetch clears it once this one imports cleanly.
            if status == "in-sync" and repo.commit.value == head:
                return
        if monotonic() >= deadline:
            break
        sleep(5)

    message = (
        f"Repository {REPOSITORY_NAME} did not import {head[:8]} within {timeout}s (status: {status}), "
        f"check `docker compose logs task-worker`"
    )
    raise Exit(message)


@task
def load(ctx: Context) -> None:
    """
    Publish the repository and load everything it does not carry itself.

    Schemas, menus and objects are declared in `.infrahub.yml`, so Infrahub imports
    them during the repository sync — they need no explicit load step.
    """
    publish_upstream(ctx)
    ctx.run("infrahubctl object load repository.yml")
    ctx.run("infrahubctl object load data/permissions.yml")
    wait_for_repository(ctx)
    # Trigger rules reference the generator definitions the repository import registers.
    ctx.run("infrahubctl object load triggers.yml")


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
