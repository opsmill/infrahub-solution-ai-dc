# Infrahub Repository

Welcome! This repository was initialized via the `uv tool run copier copy https://github.com/opsmill/infrahub-template infrahub-repo` command. That bootstraps a repository for use with some example data.

## Installation

Running `uv sync` will install all the main dependencies you need to interact with this repository.

```bash
uv sync --all-packages
source .venv/bin/activate
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

## Tests

By default there are some integration tests that will spin up Infrahub and its dependencies in docker and load the repository and schema. This can be run using the following:

```bash
uv sync --extras dev
pytest tests/integration
```

To change the version of infrahub being used you can use an environment variable: `export INFRAHUB_TESTING_IMAGE_VERSION=1.3.0`.
