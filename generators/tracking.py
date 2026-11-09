from __future__ import annotations

from typing import TYPE_CHECKING

from infrahub_sdk.node import RelationshipManager

if TYPE_CHECKING:
    from collections.abc import Iterable

    from infrahub_sdk import InfrahubClient


async def release_from_tracking_group(client: InfrahubClient, node_ids: Iterable[str]) -> None:
    """Remove nodes this generator does not own from its tracking group.

    The cleanup at the end of a run deletes every group member the run did not save, so a node
    left in the group from an earlier run would be deleted once the generator stops tracking it.
    """
    group = await client.group_context.get_group()
    if group is None:
        return
    members = group.members
    if not isinstance(members, RelationshipManager):
        return
    stale = sorted(set(node_ids) & set(members.peer_ids))
    if stale:
        await group.remove_relationships(relation_to_update="members", related_nodes=stale)
