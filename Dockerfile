ARG INFRAHUB_BASE_VERSION=1.6.0
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
