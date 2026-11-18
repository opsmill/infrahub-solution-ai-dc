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

COPY pyproject.toml README.md ./
COPY src/ src/

# Install only this package, editable so that a mounted src/ is used. Its dependencies come from the Infrahub image:
# `uv sync` would install the versions of uv.lock over the newer ones of the image, and over its infrahub-sdk.
RUN uv pip install --python /.venv/bin/python --no-deps --editable .

USER ${INFRAHUB_IMAGE_USER}

WORKDIR /source
