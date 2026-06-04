ARG INFRAHUB_BASE_VERSION=1.9.6
FROM registry.opsmill.io/opsmill/infrahub-enterprise:${INFRAHUB_BASE_VERSION}
USER root

# Use the system Python environment
ENV UV_PROJECT_ENVIRONMENT="/.venv"

WORKDIR /opt/local

COPY pyproject.toml uv.lock README.md ./
COPY src/ src/

# --no-dev is necessary to avoid installing dev dependencies including a different version of the infrahub-sdk
# --inexact is necessary to avoid uninstaling the existing infrahub environment
RUN uv sync --no-dev --frozen --inexact

WORKDIR /source
