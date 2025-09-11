# Solution AI-DC

## Installation

Running `uv sync` will install all the main dependencies you need to interact with this repository.

```bash
uv sync --all-packages
```

## Building the image

For now, we need to build Infrahub from a specific branch in the Infrahub repository.

```bash
git clone --single-branch --branch integration/generator ssh://github.com/opsmill/infrahub.git
cd infrahub
poetry install
poetry run inv dev.build
```

Next, from within this repository, build a custom image.

```bash
cd solution-ai-dc
export INFRAHUB_BASE_VERSION=local
uv run inv build
```

## Starting Infrahub

Included in the repository are a set of helper commands to get Infrahub up and running using `invoke`.

```bash
Available tasks:

  destroy                 Stop and remove containers, networks, and volumes.
  download-compose-file   Download docker-compose.yml from InfraHub if missing or override is True.
  load-schema             Load schemas into InfraHub using infrahubctl.
  restart                 Restart all services or a specific one using docker-compose.
  start                   Start the services using docker-compose in detached mode.
  stop                    Stop containers and remove networks.
  test                    Run tests using pytest.
```

To start infrahub simply use `invoke start`

