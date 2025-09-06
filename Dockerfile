# This Dockerfile serves two purposes:
# 1. It builds a custom Infrahub image with the `solution_ai_dc` python module included. It can now be imported and used within the Infrahub environment (in generators for example).

ARG INFRAHUB_BASE_VERSION=1.4.2
FROM registry.opsmill.io/opsmill/infrahub:${INFRAHUB_BASE_VERSION}

# Use the system Python environment
ENV UV_PROJECT_ENVIRONMENT="/usr/local/"

WORKDIR /opt/local

COPY pyproject.toml uv.lock README.md ./
COPY src/ src/

# --no-dev is necessary to avoid installing dev dependencies including a different version of the infrahub-sdk
# --inexact is necessary to avoid uninstaling the existing infrahub environment
RUN uv sync --no-dev --frozen --inexact

WORKDIR /source