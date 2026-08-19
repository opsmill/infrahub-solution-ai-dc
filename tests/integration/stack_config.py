"""Which image and tag the integration stack runs, resolved in one place.

A pure function over an environment mapping, so it can be tested without Docker. Do not read
``infrahub_testcontainers.container.PROJECT_ENV_VARIABLES`` instead: environment overrides reach the
deployment but are never merged back into that dict, so Python-side reads of it return the defaults.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

DEFAULT_IMAGE_REPOSITORY = "registry.opsmill.io/opsmill/infrahub"

# Both spellings feed different code paths, so anything resolving one must resolve the other.
_TAG_VARIABLES = ("INFRAHUB_TESTING_IMAGE_VER", "INFRAHUB_TESTING_IMAGE_VERSION")
_REPOSITORY_VARIABLE = "INFRAHUB_TESTING_DOCKER_IMAGE"
_PULL_VARIABLE = "INFRAHUB_TESTING_DOCKER_PULL"
_BUILD_ARG_VARIABLE = "INFRAHUB_BASE_VERSION"
_TRUTHY = frozenset({"true", "1", "yes", "on"})
_FALSY = frozenset({"false", "0", "no", "off"})


@dataclass(frozen=True)
class StackImage:
    """The image the integration stack runs, and the environment that makes every path agree.

    Attributes:
        repository: Image repository, without a tag.
        tag: Image tag, which for this stack is an Infrahub version.
        pull: Whether the stack should pull the image. False for a locally built one.
        custom_build: Whether this repository builds its own image rather than running vanilla
            Infrahub.
    """

    repository: str
    tag: str
    pull: bool
    custom_build: bool

    @property
    def reference(self) -> str:
        """Full ``repository:tag`` reference, as Docker expects it.

        Returns:
            The joined reference, suitable for ``docker image inspect``.
        """
        return f"{self.repository}:{self.tag}"

    def as_env(self) -> dict[str, str]:
        """Every variable that must be set for the fixture path and the ``.env`` writer to agree.

        Returns:
            A mapping to merge into ``os.environ`` before the stack starts.
        """
        return {
            _REPOSITORY_VARIABLE: self.repository,
            "INFRAHUB_TESTING_IMAGE_VERSION": self.tag,
            "INFRAHUB_TESTING_IMAGE_VER": self.tag,
            _PULL_VARIABLE: "true" if self.pull else "false",
        }


def resolve_stack_image(
    env: Mapping[str, str],
    packaged_version: str,
    *,
    repository: str = DEFAULT_IMAGE_REPOSITORY,
    default_tag: str = "",
    custom_build: bool = False,
) -> StackImage:
    """Decide which image the integration stack should run.

    Resolution order for the tag, most explicit first: an ``INFRAHUB_TESTING_IMAGE_VER`` or
    ``INFRAHUB_TESTING_IMAGE_VERSION`` override; then ``INFRAHUB_BASE_VERSION`` but only when
    ``custom_build``; then the repository's own ``default_tag``; then the installed package version.

    Args:
        env: Environment mapping to read overrides from, normally ``os.environ``.
        packaged_version: Installed ``infrahub-testcontainers`` version, the last-resort tag.
        repository: Image repository this stack runs. Defaults to vanilla Infrahub.
        default_tag: The repository's own committed default tag, if it pins one. Leave empty unless
            the stack must run a tag the dependency pin does not select.
        custom_build: True when this repository builds its own image. Opt-in, never inferred.

    Returns:
        The resolved image.

    Raises:
        ValueError: If the resolved tag is the ``"local"`` sentinel, which the library re-resolves
            from ``INFRAHUB_TESTING_IMAGE_VER``, or if ``INFRAHUB_TESTING_DOCKER_PULL`` holds a value
            that is neither a recognised truthy nor falsy spelling.
    """
    resolved_repository = env.get(_REPOSITORY_VARIABLE) or repository
    candidates = [env.get(name) for name in _TAG_VARIABLES]
    if custom_build:
        candidates.append(env.get(_BUILD_ARG_VARIABLE))
    candidates.extend([default_tag, packaged_version])
    tag = next(candidate for candidate in candidates if candidate)

    if tag == "local":
        msg = (
            "resolved tag is the 'local' sentinel, which infrahub-testcontainers re-resolves from "
            "INFRAHUB_TESTING_IMAGE_VER; set an explicit tag instead"
        )
        raise ValueError(msg)

    explicit_pull = env.get(_PULL_VARIABLE, "").strip().lower()
    if explicit_pull and explicit_pull not in _TRUTHY | _FALSY:
        msg = f"{_PULL_VARIABLE}={explicit_pull!r} is not a recognised boolean"
        raise ValueError(msg)
    pull = explicit_pull in _TRUTHY if explicit_pull else not custom_build
    return StackImage(
        repository=resolved_repository,
        tag=tag,
        pull=pull,
        custom_build=custom_build,
    )
