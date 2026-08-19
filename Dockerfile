ARG INFRAHUB_BASE_IMAGE=registry.opsmill.io/opsmill/infrahub
# No default on purpose: `inv build` passes the version derived from the installed infrahub-testcontainers.
ARG INFRAHUB_BASE_VERSION
FROM ${INFRAHUB_BASE_IMAGE}:${INFRAHUB_BASE_VERSION}

# The Enterprise image runs as the unprivileged `infrahub` user over a root-owned /.venv, so the sync
# below has to run as root and hand the image back to that user afterwards. Community runs as root
# throughout, which is what the default covers.
ARG INFRAHUB_IMAGE_USER=root

# Use the system Python environment
ENV UV_PROJECT_ENVIRONMENT="/.venv"

USER root

WORKDIR /opt/local

COPY pyproject.toml uv.lock README.md ./
COPY src/ src/

# --no-dev is necessary to avoid installing dev dependencies including a different version of the infrahub-sdk
# --inexact is necessary to avoid uninstaling the existing infrahub environment
RUN uv sync --no-dev --frozen --inexact

USER ${INFRAHUB_IMAGE_USER}

WORKDIR /source
