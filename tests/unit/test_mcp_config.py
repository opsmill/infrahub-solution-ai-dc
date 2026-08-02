"""Guards the MCP sidecar configuration invariants (see specs/004-mcp-sidecar/plan.md)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
MCP_CONFIG_FILE = REPO_ROOT / ".mcp.json"
COMPOSE_OVERRIDE_FILE = REPO_ROOT / "docker-compose.override.yml"

MCP_SERVICE_NAME = "infrahub-mcp"
SERVICE_INDENT = 2
CREDENTIAL_KEYWORDS = ("token", "password", "username")

# The public demo token in docker-compose.yml's INFRAHUB_INITIAL_ADMIN_TOKEN default. It is
# the only literal FR-002 permits as the client-config fallback.
DEMO_TOKEN = "06438eb2-8019-4776-878c-0941b1f1d1ec"  # noqa: S105 — pinning this literal is the assertion

# Keys that pull configuration in from somewhere this line-scanning test cannot see. Three of
# the four other services in the compose override file already use the anchor merge, so this
# is the likeliest way a credential would arrive unnoticed.
OPAQUE_KEYS = ("<<", "env_file", "secrets")


def _load_mcp_servers() -> dict[str, Any]:
    """Parse .mcp.json as strict JSON and return its server registry."""
    servers = json.loads(MCP_CONFIG_FILE.read_text(encoding="utf-8"))["mcpServers"]
    assert isinstance(servers, dict)
    return servers


def _mcp_service_lines() -> list[str]:
    """Return the lines of the infrahub-mcp service block from the compose override file."""
    lines = COMPOSE_OVERRIDE_FILE.read_text(encoding="utf-8").splitlines()
    header = f"{' ' * SERVICE_INDENT}{MCP_SERVICE_NAME}:"
    assert header in lines, f"no `{MCP_SERVICE_NAME}:` service at {SERVICE_INDENT}-space indent in {COMPOSE_OVERRIDE_FILE.name}"
    start = lines.index(header) + 1

    block: list[str] = []
    for line in lines[start:]:
        if line.strip() and len(line) - len(line.lstrip()) <= SERVICE_INDENT:
            break
        block.append(line)
    return block


def _declared_keys(lines: list[str]) -> set[str]:
    """Collect every key declared in a block of YAML lines, ignoring values."""
    keys: set[str] = set()
    for line in lines:
        key, separator, _ = line.partition(":")
        if separator:
            keys.add(key.strip().removeprefix("- ").strip())
    return keys


def test_mcp_json_registers_infrahub_over_http() -> None:
    """FR-008: .mcp.json parses as strict JSON and registers `infrahub` as an HTTP server."""
    servers = _load_mcp_servers()
    assert list(servers) == ["infrahub"]
    assert servers["infrahub"]["type"] == "http"


def test_mcp_json_sources_token_from_environment() -> None:
    """FR-002: the Authorization header references ${INFRAHUB_API_TOKEN}."""
    headers = _load_mcp_servers()["infrahub"]["headers"]
    assert "${INFRAHUB_API_TOKEN" in headers["Authorization"]


def test_mcp_json_fallback_token_is_the_demo_token() -> None:
    """FR-002: any inline fallback grants nothing beyond a local throwaway demo stack.

    Checked separately from the environment reference above, because a substring check for
    ${INFRAHUB_API_TOKEN} passes just as happily when the `:-default` behind it has been
    swapped for a real credential.
    """
    authorization = _load_mcp_servers()["infrahub"]["headers"]["Authorization"]
    fallback = authorization.partition(":-")[2].removesuffix("}")
    assert fallback in ("", DEMO_TOKEN), "the only literal permitted as a fallback is the public demo token"


def test_mcp_service_declares_no_credential_keys() -> None:
    """FR-001: the sidecar service declares no token/password/username key.

    Key names only: the service legitimately sets INFRAHUB_MCP_AUTH_MODE to
    `token-passthrough`, whose value contains "token".
    """
    keys = _declared_keys(_mcp_service_lines())
    assert "image" in keys, "infrahub-mcp service block parsed as empty"

    offenders = sorted(key for key in keys if any(word in key.lower() for word in CREDENTIAL_KEYWORDS))
    assert offenders == []


def test_mcp_service_pulls_in_no_opaque_configuration() -> None:
    """Keeps the FR-001 scan honest: fail loudly rather than silently miss a credential.

    The scan above reads `key: value` lines in one service block, so configuration merged in
    from a YAML anchor, an env_file, or a secrets mount would be invisible to it. If the
    service ever grows one of those, this fails and whoever added it has to teach the
    credential scan to follow it.
    """
    keys = _declared_keys(_mcp_service_lines())
    assert sorted(keys & set(OPAQUE_KEYS)) == []
