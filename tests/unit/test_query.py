"""Tests for reading required values out of a parsed generator query."""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from infrahub_solution_ai_dc.query import only_node, related, related_id, value_of


@dataclass
class _Attr:
    value: str | None = None


@dataclass
class _Node:
    id: str | None = "node-1"


@dataclass
class _Rel:
    node: _Node | None = None


@dataclass
class _Edge:
    node: _Node | None = field(default_factory=_Node)


class TestValueOf:
    def test_a_present_value_is_returned(self) -> None:
        assert value_of(_Attr("pod-a1"), field="name", of="pod 1") == "pod-a1"

    def test_an_unselected_attribute_fails_loud(self) -> None:
        """The attribute itself absent and its value null are the same data gap from here."""
        with pytest.raises(ValueError, match="Cannot read name of pod 1"):
            value_of(None, field="name", of="pod 1")

    def test_a_null_value_fails_loud(self) -> None:
        with pytest.raises(ValueError, match="Cannot read name of pod 1"):
            value_of(_Attr(None), field="name", of="pod 1")

    def test_the_message_names_the_field_and_the_object(self) -> None:
        """An operator reads this in a task worker log with no other context."""
        with pytest.raises(ValueError) as raised:
            value_of(_Attr(None), field="amount_of_spines", of="pod pod-a1")

        assert "amount_of_spines" in str(raised.value)
        assert "pod pod-a1" in str(raised.value)


class TestRelated:
    def test_a_present_node_is_returned(self) -> None:
        node = _Node("fabric-1")

        assert related(_Rel(node), field="parent", of="pod 1") is node

    def test_an_unset_relationship_fails_loud(self) -> None:
        with pytest.raises(ValueError, match="Cannot read parent of pod 1"):
            related(_Rel(None), field="parent", of="pod 1")

    def test_an_unselected_relationship_fails_loud(self) -> None:
        with pytest.raises(ValueError, match="Cannot read parent of pod 1"):
            related(None, field="parent", of="pod 1")


class TestRelatedId:
    def test_the_id_is_returned(self) -> None:
        assert related_id(_Rel(_Node("fabric-1")), field="parent", of="pod 1") == "fabric-1"

    def test_a_node_without_an_id_fails_loud(self) -> None:
        """The second unchecked hop the old ``type: ignore[assignment]`` hid."""
        with pytest.raises(ValueError, match="the related node has no id"):
            related_id(_Rel(_Node(None)), field="parent", of="pod 1")

    def test_an_unset_relationship_fails_loud(self) -> None:
        with pytest.raises(ValueError, match="Cannot read parent of pod 1"):
            related_id(_Rel(None), field="parent", of="pod 1")


class TestOnlyNode:
    def test_the_single_selected_node_is_returned(self) -> None:
        node = _Node("pod-1")

        assert only_node([_Edge(node)], of="the pod") is node

    def test_an_empty_result_fails_loud(self) -> None:
        """The trigger fired for something the query could not find — a message, not an IndexError."""
        with pytest.raises(ValueError, match="Cannot read the pod: the query matched no node"):
            only_node([], of="the pod")

    def test_an_edge_with_no_node_fails_loud(self) -> None:
        with pytest.raises(ValueError, match="the query matched no node"):
            only_node([_Edge(None)], of="the pod")

    def test_the_first_edge_wins(self) -> None:
        """A generator is dispatched for one design object; extra edges are not its business."""
        first = _Node("pod-1")

        assert only_node([_Edge(first), _Edge(_Node("pod-2"))], of="the pod") is first
