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


def _load_mcp_servers() -> dict[str, Any]:
    """Parse .mcp.json as strict JSON and return its server registry."""
    servers = json.loads(MCP_CONFIG_FILE.read_text(encoding="utf-8"))["mcpServers"]
    assert isinstance(servers, dict)
    return servers


def _mcp_service_lines() -> list[str]:
    """Return the lines of the infrahub-mcp service block from the compose override file."""
    lines = COMPOSE_OVERRIDE_FILE.read_text(encoding="utf-8").splitlines()
    header = f"{' ' * SERVICE_INDENT}{MCP_SERVICE_NAME}:"
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
    """FR-002: the Authorization header takes the token from the environment, not a literal."""
    headers = _load_mcp_servers()["infrahub"]["headers"]
    assert "${INFRAHUB_API_TOKEN" in headers["Authorization"]


def test_mcp_service_declares_no_credential_keys() -> None:
    """FR-001: the sidecar service is configured with no Infrahub credential of any kind."""
    keys = _declared_keys(_mcp_service_lines())
    assert "image" in keys, "infrahub-mcp service block not found or not parsed"

    offenders = sorted(key for key in keys if any(word in key.lower() for word in CREDENTIAL_KEYWORDS))
    assert offenders == []
