ARG INFRAHUB_BASE_VERSION=1.10.0
FROM registry.opsmill.io/opsmill/infrahub:${INFRAHUB_BASE_VERSION}

# The base image no longer ships uv, so pull the binary from the official
# Astral image (pinned to the version the base image previously bundled).
COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /uvx /usr/local/bin/

# Use the system Python environment
ENV UV_PROJECT_ENVIRONMENT="/.venv"

WORKDIR /opt/local

COPY pyproject.toml uv.lock README.md ./
COPY src/ src/

# --no-dev is necessary to avoid installing dev dependencies including a different version of the infrahub-sdk
# --inexact is necessary to avoid uninstaling the existing infrahub environment
RUN uv sync --no-dev --frozen --inexact

WORKDIR /source
