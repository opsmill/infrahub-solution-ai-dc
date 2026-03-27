---
name: upgrade-infrahub
description: >
  Upgrade the Infrahub platform version in this project. Handles downloading the new compose file,
  upgrading the SDK, updating version references across Dockerfile, docker-compose.override.yml,
  and .envrc, and rebuilding the Docker image. Use this skill whenever the user asks to upgrade,
  bump, or update the Infrahub version — even if they just say something like "bump infrahub to 1.9"
  or "upgrade to latest infrahub" or "update infrahub version".
---

# Upgrade Infrahub

This skill upgrades the Infrahub platform version across the project. The version appears in several
files and needs to stay in sync — this skill handles all of them in the right order.

## Step 1: Get the target version

If the user provided a version (e.g., "upgrade to 1.8.2"), use it. Otherwise, ask them which version
to upgrade to before proceeding.

The version should be a semver string like `1.8.2` — no `v` prefix.

## Step 2: Download the new compose file

```bash
uv run invoke download-compose-file --override --infrahub-version <VERSION>
```

This fetches the `docker-compose.yml` for the target Infrahub version from the Infrahub registry.

## Step 3: Upgrade the SDK

```bash
uv lock --upgrade infrahub-sdk
```

Then sync all dependency groups:

```bash
uv sync --all-groups
```

These two commands ensure the `infrahub-sdk` package is updated to the latest compatible version and
all dependencies are installed.

## Step 4: Update version references in project files

Three files contain the Infrahub version and need to be updated:

### Dockerfile

In the root `Dockerfile`, update the `INFRAHUB_BASE_VERSION` build arg on the first line:

```dockerfile
ARG INFRAHUB_BASE_VERSION=<VERSION>
```

### docker-compose.override.yml

In `docker-compose.override.yml`, update every occurrence of the old version in the
`INFRAHUB_BASE_VERSION` default values. There are two places:

1. The image tag: `image: opsmill/infrahub-solution-ai-dc:${INFRAHUB_BASE_VERSION:-<VERSION>}`
2. The build arg: `INFRAHUB_BASE_VERSION: "${INFRAHUB_BASE_VERSION:-<VERSION>}"`

### .envrc (conditional)

Only if `.envrc` exists in the project root **and** contains a `VERSION=` line, update it:

```bash
export VERSION="<VERSION>"
```

If `.envrc` doesn't exist or doesn't define `VERSION`, skip this file.

## Step 5: Reload environment

```bash
direnv allow
```

This reloads the environment variables from `.envrc` so the new version takes effect in the shell.

## Step 6: Rebuild the Docker image

```bash
uv run inv build
```

This rebuilds the Docker image with the new Infrahub base version. This step can take a while —
let the user know it's running.
