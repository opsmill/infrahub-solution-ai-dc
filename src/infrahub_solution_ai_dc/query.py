"""Reading required values out of a parsed generator query.

The generated ``*_query.py`` models type every field as optional, and they are right to: Infrahub's
GraphQL schema is nullable, and a design object mid-cascade genuinely returns a null relationship.
But a generator's own ``.gql`` file selects exactly what that generator cannot run without, so at the
point of reading, "absent" is not a case to handle — it is a data gap to report.

Generators used to say that with ``assert`` and silence mypy with ``type: ignore[union-attr]`` at
every hop. An ``assert`` raises ``AssertionError`` with no message, in a background task worker, and
is removed entirely under ``python -O``. These helpers say the same thing as a ``ValueError`` naming
the design object and the field that was missing, and give mypy the narrowing it was being told to
ignore.

They cover the *read* side only. A ``type: ignore`` on a **write** — assigning a ``CoreNumberPool`` to
an attribute's ``value`` so the server allocates from it, or a node to a relationship — is a genuine
SDK idiom, not a nullability workaround, and is left alone.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, TypeVar

if TYPE_CHECKING:
    from collections.abc import Sequence

_T_co = TypeVar("_T_co", covariant=True)


class Attribute(Protocol[_T_co]):
    """An attribute leaf of a parsed query result — ``{"value": ...}``."""

    @property
    def value(self) -> _T_co | None: ...


class Relationship(Protocol[_T_co]):
    """A to-one relationship of a parsed query result — ``{"node": {...}}``."""

    @property
    def node(self) -> _T_co | None: ...


class Edge(Protocol[_T_co]):
    """One edge of a to-many relationship or a top-level query result."""

    @property
    def node(self) -> _T_co | None: ...


def value_of(attribute: Attribute[_T_co] | None, *, field: str, of: str) -> _T_co:
    """Return a required attribute's value, or fail loud naming what was missing.

    Covers both ways the value can be absent — the attribute itself unselected, or selected and null
    — because from the generator's side they are the same data gap.
    """
    value = attribute.value if attribute is not None else None
    if value is None:
        msg = f"Cannot read {field} of {of}: the query returned no value for it"
        raise ValueError(msg)
    return value


def related(relationship: Relationship[_T_co] | None, *, field: str, of: str) -> _T_co:
    """Return a required to-one relationship's node, or fail loud naming what was missing.

    Chain it a hop at a time rather than dereferencing straight through, so a half-built graph says
    *which* hop was empty — a tenant with no fabric reads differently from a service with no tenant.
    """
    node = relationship.node if relationship is not None else None
    if node is None:
        msg = f"Cannot read {field} of {of}: the query returned no related node for it"
        raise ValueError(msg)
    return node


class Node(Protocol):
    """Any parsed node, which carries an id — itself optional in the generated models."""

    @property
    def id(self) -> str | None: ...


def related_id(relationship: Relationship[Node] | None, *, field: str, of: str) -> str:
    """Return the id of a required to-one relationship's node, or fail loud.

    The common shape, and the one the old ``type: ignore[assignment]`` hid most: the node's own ``id``
    is optional too, so dereferencing straight through was two unchecked hops rather than one.
    """
    node_id = related(relationship, field=field, of=of).id
    if node_id is None:
        msg = f"Cannot read {field} of {of}: the related node has no id"
        raise ValueError(msg)
    return node_id


def only_node(edges: Sequence[Edge[_T_co]], *, of: str) -> _T_co:
    """Return the node of the single edge a generator's query selected, or fail loud.

    A generator is dispatched for one design object, so an empty result means the trigger fired for
    something the query could not find — worth a message rather than an ``IndexError``.
    """
    node = edges[0].node if edges else None
    if node is None:
        msg = f"Cannot read {of}: the query matched no node"
        raise ValueError(msg)
    return node
