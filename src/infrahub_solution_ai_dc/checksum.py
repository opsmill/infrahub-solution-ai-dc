"""The checksum a generator stamps to declare what it produced.

A checksum is what makes the generator cascade run: ``triggers.yml`` watches the ``checksum``
attribute of every ``GeneratorTarget``, so stamping a new value on a node is how one generator asks
the next one to run. Two facts follow, and both live here rather than in each generator:

- **A stamp is written only when the digest actually changes.** A generator that re-stamps an
  unchanged value re-fires its own trigger, and the cascade never settles.
- **Whether the stamped node joins the generator's group is the caller's decision**, never a
  default. Group membership is what the generator's cleanup prunes against, so tracking a node the
  generator does not own means the first run that stops producing it *deletes* it.

Two id sources feed the same digest, and the choice between them is the choice of what "changed"
means for that generator:

- :meth:`Checksum.over_session` — everything the run touched, read off the SDK's group context. The
  physical cascade uses it: a fabric or pod run that touched a different set of objects should
  re-drive the tier below it.
- :meth:`Checksum.over_contents` — an explicit set of ids the caller names. The overlay and server
  generators use it, because what should re-trigger them is a change in the objects they
  materialized, not in whatever else the run happened to read.

``RackGenerator`` stamps nothing, and that is deliberate rather than an omission: the rack is the
last tier of the cascade (fabric -> pod -> rack), so there is no tier below it to drive.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import logging
    from collections.abc import Iterable

    from infrahub_sdk.client import InfrahubClient

    from .protocols import GeneratorTarget


def _digest_of(ids: Iterable[str]) -> str:
    """Hash an id set order-independently, so only its *membership* moves the digest."""
    return hashlib.sha256(",".join(sorted(ids)).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Checksum:
    """A digest over the ids a generator run is defined by, and the stamping rule that goes with it."""

    digest: str

    @classmethod
    def over_session(cls, client: InfrahubClient) -> Checksum:
        """Digest everything the run touched, from the SDK group context.

        Read at the point of the call, so a generator that allocates further objects afterwards keeps
        them out of the digest — which is how ``FabricGenerator`` stamps the pods before doing its
        overlay work without re-triggering the cascade a second time (ADR-0004).
        """
        group_context = client.group_context
        return cls(_digest_of(group_context.related_group_ids + group_context.related_node_ids))

    @classmethod
    def over_contents(cls, object_ids: Iterable[str]) -> Checksum:
        """Digest an explicit id set — the objects the caller considers its output."""
        return cls(_digest_of(object_ids))

    async def stamp_on(
        self,
        targets: Iterable[GeneratorTarget],
        *,
        logger: logging.Logger,
        track: bool | None,
    ) -> int:
        """Write this digest onto every target whose checksum differs, and report how many changed.

        ``track`` is the SDK's ``update_group_context``, and has no default so that every caller
        states its answer:

        - ``False`` — never add the target to the generator's group. Correct whenever the generator
          does not own what it is stamping, which is the case for both design objects stamped here.
        - ``None`` — defer to the client's mode, which adds the target only when the client is
          ``TRACKING``. What the physical cascade has always done, since it saved without passing
          the argument at all.
        - ``True`` — always add it.

        Returns the number of targets written, so a caller can tell a settled re-run (``0``) from
        one that drove the next tier.
        """
        changed = 0
        for target in targets:
            if target.checksum.value == self.digest:
                continue
            target.checksum.value = self.digest
            await target.save(allow_upsert=True, update_group_context=track)
            label = getattr(target, "display_label", None) or target.id
            logger.info(f"Stamped checksum {self.digest} on {label}")
            changed += 1
        return changed
