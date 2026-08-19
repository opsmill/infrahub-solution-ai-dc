"""Stack image resolution, which decides what the integration suite actually tests.

Marked ``offline``: this reads no deployment, only the resolution logic.
"""

from __future__ import annotations

import pytest

from .stack_config import DEFAULT_IMAGE_REPOSITORY, StackImage, resolve_stack_image

pytestmark = pytest.mark.offline

PACKAGED = "1.11.0"


def test_defaults_to_the_vanilla_image_at_the_packaged_version() -> None:
    """With no overrides the suite tests the version the dependency pin selects."""
    resolved = resolve_stack_image({}, PACKAGED)
    assert resolved.repository == DEFAULT_IMAGE_REPOSITORY
    assert resolved.tag == PACKAGED
    assert resolved.pull is True
    assert resolved.custom_build is False


def test_repository_override_is_honoured() -> None:
    """A custom-image repository must be able to redirect the stack away from vanilla Infrahub."""
    resolved = resolve_stack_image({"INFRAHUB_TESTING_DOCKER_IMAGE": "opsmill/custom"}, PACKAGED)
    assert resolved.repository == "opsmill/custom"


def test_repository_argument_is_honoured() -> None:
    """A repository can name its image in its conftest header instead of through the environment."""
    resolved = resolve_stack_image({}, PACKAGED, repository="opsmill/custom")
    assert resolved.repository == "opsmill/custom"


@pytest.mark.parametrize("variable", ["INFRAHUB_TESTING_IMAGE_VER", "INFRAHUB_TESTING_IMAGE_VERSION"])
def test_either_tag_variable_is_honoured(variable: str) -> None:
    """Both spellings exist in the wild; the canonical resolver accepts either."""
    assert resolve_stack_image({variable: "1.12.0"}, PACKAGED).tag == "1.12.0"


def test_image_ver_wins_over_image_version() -> None:
    """_VER is the testcontainers-native knob, so it is the more specific of the two."""
    env = {"INFRAHUB_TESTING_IMAGE_VER": "1.12.0", "INFRAHUB_TESTING_IMAGE_VERSION": "1.11.9"}
    assert resolve_stack_image(env, PACKAGED).tag == "1.12.0"


def test_default_tag_beats_the_packaged_version() -> None:
    """A repository pinning its own committed default is not overridden by the installed package."""
    assert resolve_stack_image({}, PACKAGED, default_tag="1.11.1").tag == "1.11.1"


def test_explicit_env_beats_the_default_tag() -> None:
    """An override is an override; nothing in the repository outranks it."""
    env = {"INFRAHUB_TESTING_IMAGE_VER": "1.12.0"}
    assert resolve_stack_image(env, PACKAGED, default_tag="1.11.1").tag == "1.12.0"


def test_base_version_is_read_only_for_a_custom_build() -> None:
    """INFRAHUB_BASE_VERSION is the custom image's build arg, not a knob on the vanilla stack."""
    env = {"INFRAHUB_BASE_VERSION": "1.10.0"}
    assert resolve_stack_image(env, PACKAGED).tag == PACKAGED
    assert resolve_stack_image(env, PACKAGED, custom_build=True).tag == "1.10.0"


def test_custom_build_defaults_to_not_pulling() -> None:
    """A locally built image is not in a registry, so pulling it would fail."""
    resolved = resolve_stack_image({}, PACKAGED, custom_build=True)
    assert resolved.pull is False
    assert resolved.custom_build is True


@pytest.mark.parametrize("value", ["false", "0", "no", "off", "FALSE", " false "])
def test_explicit_falsy_pull_wins_over_the_vanilla_default(value: str) -> None:
    """The environment stays the final say, consistent with tag resolution."""
    assert resolve_stack_image({"INFRAHUB_TESTING_DOCKER_PULL": value}, PACKAGED).pull is False


@pytest.mark.parametrize("value", ["true", "1", "yes", "on", "TRUE", " true "])
def test_explicit_truthy_pull_wins_over_the_custom_build_default(value: str) -> None:
    """`1` is the conventional spelling for a Docker-adjacent boolean, so it must not read as false."""
    env = {"INFRAHUB_TESTING_DOCKER_PULL": value}
    assert resolve_stack_image(env, PACKAGED, custom_build=True).pull is True


def test_unrecognised_pull_value_is_rejected() -> None:
    """Guessing an unparseable boolean would fail silently; refusing it fails loudly."""
    with pytest.raises(ValueError, match="not a recognised boolean"):
        resolve_stack_image({"INFRAHUB_TESTING_DOCKER_PULL": "maybe"}, PACKAGED)


def test_reference_joins_repository_and_tag() -> None:
    """The reference is what Docker is handed."""
    assert StackImage("opsmill/custom", "1.12.0", pull=False, custom_build=True).reference == "opsmill/custom:1.12.0"


def test_as_env_sets_both_tag_variables_to_the_same_value() -> None:
    """The whole point: one resolution, every path agreeing."""
    env = resolve_stack_image({}, PACKAGED, repository="opsmill/custom", custom_build=True).as_env()
    assert env == {
        "INFRAHUB_TESTING_DOCKER_IMAGE": "opsmill/custom",
        "INFRAHUB_TESTING_IMAGE_VERSION": PACKAGED,
        "INFRAHUB_TESTING_IMAGE_VER": PACKAGED,
        "INFRAHUB_TESTING_DOCKER_PULL": "false",
    }


def test_blank_values_are_treated_as_unset() -> None:
    """An unset GitHub Actions input arrives as an empty string, not as a missing key."""
    env = {"INFRAHUB_TESTING_DOCKER_IMAGE": "", "INFRAHUB_TESTING_IMAGE_VER": ""}
    resolved = resolve_stack_image(env, PACKAGED)
    assert resolved.repository == DEFAULT_IMAGE_REPOSITORY
    assert resolved.tag == PACKAGED


def test_local_sentinel_is_rejected() -> None:
    """ "local" makes the library re-resolve the tag, so returning it would be a lie."""
    with pytest.raises(ValueError, match="local"):
        resolve_stack_image({"INFRAHUB_TESTING_IMAGE_VER": "local"}, PACKAGED)
