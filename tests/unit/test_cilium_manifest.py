"""Tests for the rendered Cilium manifest (transforms/cilium_manifest.py) — US1, US2 and US3 unit tests.

The manifest is the **published contract with Vidra**: every value asserted here is applied verbatim
to a Kubernetes cluster, so the assertions mirror ``contracts/cilium-manifest-artifact.md`` field for
field.

Two deliberate choices:

- **The fixture is a raw GraphQL result**, exactly the shape ``transforms/cilium_manifest.gql``
  returns, and it is driven through the whole transform body (parse → peering module → render). So
  these tests cover the query response model and the peering module's integration with the renderer,
  not just the dict building.
- **Assertions are on parsed structure**, via ``yaml.safe_load_all`` — never on rendered whitespace,
  key order within a document, or template internals. Cilium reads the parsed documents; so do we.

The US2 classes (:class:`TestMemberCountDifferencing`, :class:`TestMemberMove`) verify one half of
FR-006 only: that the body is a pure *function* of the cluster's members, so adding, removing or moving
one changes exactly what it should. That Infrahub re-renders the artifact at all when a member changes
rests on artifact data-dependency tracking (``research.md`` R7) and is verified manually via
``quickstart.md`` step 6 — nothing here tests it.

The US3 classes at the bottom (:class:`TestMixedCluster`, :class:`TestIncompleteMember`,
:class:`TestEmptyCluster`) assert the *rendered* consequences of exclusion. Which members are eligible,
and why each is dropped, is tests/unit/test_clusters.py; here it is only that the body is what remains.
"""

from __future__ import annotations

from copy import deepcopy
from typing import TYPE_CHECKING, Any

import yaml

from transforms.cilium_manifest import cluster_member_facts, render_cluster_manifest
from transforms.cilium_manifest_query import CiliumManifestQuery

if TYPE_CHECKING:
    from infrahub_solution_ai_dc.clusters import MemberFacts

#: The leaf's local AS in the seeded fabric — every member's ``remote_as`` and so every ``peerASN``.
OVERLAY_ASN = 65000


def _leaf_endpoint(address: str | None) -> dict[str, Any]:
    """The leaf end of a member's attachment link — the only end carrying ``peerAddress``.

    ``address=None`` models a cabled port with no IP allocated yet, which the query returns as a null
    ``ip_address`` node.
    """
    node = {"id": f"leaf-ip-{address}", "address": {"value": address}} if address is not None else None
    return {
        "id": f"leaf-interface-{address}",
        "__typename": "NetworkInterface",
        "ip_address": {"node": node},
    }


def _server_endpoint(interface_id: str) -> dict[str, Any]:
    """The member's own end of the link.

    It carries no ``ip_address`` because the query's inline fragment selects one only ``on
    NetworkInterface`` — so a renderer that took the wrong end would resolve no address at all and the
    member would silently vanish from the body, which the document-count assertions catch.
    """
    return {"id": interface_id, "__typename": "ServerInterface"}


def _member(
    name: str,
    *,
    layer: str = "l3",
    node_selector: str | None = None,
    local_as: int | None = 4200000001,
    remote_as: int = OVERLAY_ASN,
    leaf_address: str | None = "10.0.0.1/31",
    interface_name: str = "eth1",
) -> dict[str, Any]:
    """One ``members`` edge: a fully provisioned L3 member unless a field is overridden away.

    ``node_selector`` defaults to the service name, as the computed attribute yields for a server the
    generator named ``server-<service>``.
    """
    interface_id = f"{name}-{interface_name}"
    return {
        "node": {
            "id": f"service-{name}",
            "name": {"value": name},
            "layer": {"value": layer},
            "server": {
                "node": {
                    "id": f"server-{name}",
                    "hostname": {"value": f"server-{name}"},
                    "node_selector": {"value": node_selector if node_selector is not None else name},
                    "asn": {"value": local_as},
                    "bgp_sessions": {
                        "edges": [
                            {
                                "node": {
                                    "id": f"session-{name}",
                                    "address_family": {"value": "ipv4_unicast"},
                                    "local_as": {"value": local_as},
                                    "remote_as": {"value": remote_as},
                                }
                            }
                        ]
                    },
                    "interfaces": {
                        "edges": [
                            {
                                "node": {
                                    "id": interface_id,
                                    "name": {"value": interface_name},
                                    "link": {
                                        "node": {
                                            "id": f"link-{name}",
                                            "endpoints": {
                                                "edges": [
                                                    {"node": _server_endpoint(interface_id)},
                                                    {"node": _leaf_endpoint(leaf_address)},
                                                ]
                                            },
                                        }
                                    },
                                }
                            }
                        ]
                    },
                }
            },
        }
    }


def _cluster_result(members: list[dict[str, Any]], name: str = "cilium-demo") -> dict[str, Any]:
    """The ``cilium_manifest`` query result for one cluster holding ``members``."""
    return {
        "NetworkKubernetesCluster": {
            "edges": [
                {
                    "node": {
                        "id": f"cluster-{name}",
                        "name": {"value": name},
                        "members": {"edges": members},
                    }
                }
            ]
        }
    }


def _body(members: list[dict[str, Any]]) -> str:
    """Render the manifest for ``members`` and return the raw body text.

    Used only where the assertion is genuinely about the *whole text* — "this string appears nowhere"
    cannot be expressed against the parsed documents, since a leaked selector could surface in any
    field of any document.
    """
    return render_cluster_manifest(_cluster_result(members))


def _documents(members: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Render the manifest for ``members`` and return its parsed documents."""
    return list(yaml.safe_load_all(_body(members)))


def _two_l3_members() -> list[dict[str, Any]]:
    """Two eligible L3 members on different leaves — the US1 fixture (N = 2)."""
    return [
        _member("cilium-worker-1", local_as=4200000001, leaf_address="10.0.0.1/31"),
        _member("cilium-worker-2", local_as=4200000002, leaf_address="10.0.0.3/31"),
    ]


def _three_l3_members() -> list[dict[str, Any]]:
    """The US1 fixture grown by one member — the N + 1 side of the US2 differencing tests (N = 3)."""
    return [
        *_two_l3_members(),
        _member("cilium-worker-3", local_as=4200000003, leaf_address="10.0.0.5/31"),
    ]


def _of_kind(documents: list[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
    """The rendered documents of one Cilium kind, in render order."""
    return [document for document in documents if document["kind"] == kind]


def _shared_documents(documents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The two documents that are shared across the whole cluster, independent of its members."""
    return _of_kind(documents, "CiliumBGPPeerConfig") + _of_kind(documents, "CiliumBGPAdvertisement")


def _expected_cluster_config(node_selector: str, local_asn: int, peer_address: str) -> dict[str, Any]:
    """The ``CiliumBGPClusterConfig`` contracts/cilium-manifest-artifact.md §1 specifies."""
    return {
        "apiVersion": "cilium.io/v2",
        "kind": "CiliumBGPClusterConfig",
        "metadata": {"name": node_selector},
        "spec": {
            "nodeSelector": {"matchLabels": {"infrahub.io/server": node_selector}},
            "bgpInstances": [
                {
                    "name": f"instance-{local_asn}",
                    "localASN": local_asn,
                    "peers": [
                        {
                            "name": f"peer-{OVERLAY_ASN}-leaf",
                            "peerASN": OVERLAY_ASN,
                            "peerAddress": peer_address,
                            "peerConfigRef": {"name": "cilium-peer"},
                        }
                    ],
                }
            ],
        },
    }


class TestDocumentSet:
    """The body's shape: N + 2 documents, fixed kinds, fixed order (FR-003)."""

    def test_two_members_render_n_plus_two_documents(self) -> None:
        """One cluster config per eligible member, plus the two shared documents."""
        documents = _documents(_two_l3_members())

        assert len(documents) == len(_two_l3_members()) + 2

    def test_kinds_are_in_the_contracted_order(self) -> None:
        """Cluster configs first, then the peer config, then the advertisement.

        The order is fixed so an unchanged fabric renders byte-identically — the property Vidra's
        checksum comparison depends on.
        """
        documents = _documents(_two_l3_members())

        assert [document["kind"] for document in documents] == [
            "CiliumBGPClusterConfig",
            "CiliumBGPClusterConfig",
            "CiliumBGPPeerConfig",
            "CiliumBGPAdvertisement",
        ]

    def test_cluster_configs_are_ordered_by_node_selector(self) -> None:
        """Ordering holds regardless of the order the query returned the members in."""
        reversed_members = list(reversed(_two_l3_members()))

        documents = _documents(reversed_members)

        assert [document["metadata"]["name"] for document in documents[:2]] == [
            "cilium-worker-1",
            "cilium-worker-2",
        ]

    def test_every_document_is_a_cilium_v2_resource(self) -> None:
        """``cilium.io/v2`` — the v2alpha1 resource set is superseded."""
        documents = _documents(_two_l3_members())

        assert {document["apiVersion"] for document in documents} == {"cilium.io/v2"}


class TestClusterConfig:
    """Every field of every ``CiliumBGPClusterConfig``, against the stored session and leaf address."""

    def test_both_cluster_configs_match_the_contract_field_for_field(self) -> None:
        """``localASN`` is the member's own ASN and ``peerASN`` the leaf's — per-member, never shared."""
        first, second = _documents(_two_l3_members())[:2]

        assert first == _expected_cluster_config("cilium-worker-1", 4200000001, "10.0.0.1")
        assert second == _expected_cluster_config("cilium-worker-2", 4200000002, "10.0.0.3")

    def test_peer_address_has_no_prefix_length(self) -> None:
        """The stored address is ``10.0.0.1/31``; Cilium rejects the CIDR form."""
        documents = _documents(_two_l3_members())

        peers = [document["spec"]["bgpInstances"][0]["peers"][0] for document in documents[:2]]

        assert [peer["peerAddress"] for peer in peers] == ["10.0.0.1", "10.0.0.3"]

    def test_local_port_is_omitted(self) -> None:
        """Setting it makes Cilium listen, which needs a capability this feature does not grant."""
        documents = _documents(_two_l3_members())

        assert all("localPort" not in document["spec"]["bgpInstances"][0] for document in documents[:2])

    def test_peer_config_ref_carries_only_a_name(self) -> None:
        """``group``/``kind`` are omitted so Cilium's defaults apply."""
        documents = _documents(_two_l3_members())

        peer_config_ref = documents[0]["spec"]["bgpInstances"][0]["peers"][0]["peerConfigRef"]

        assert peer_config_ref == {"name": "cilium-peer"}


class TestSharedDocuments:
    """The single peer config and single advertisement, and the two references that tie them in."""

    def test_peer_config_matches_the_contract(self) -> None:
        """``ipv4``/``unicast`` mirrors the stored session's ``ipv4_unicast`` address family."""
        peer_config = _documents(_two_l3_members())[2]

        assert peer_config == {
            "apiVersion": "cilium.io/v2",
            "kind": "CiliumBGPPeerConfig",
            "metadata": {"name": "cilium-peer"},
            "spec": {
                "families": [
                    {
                        "afi": "ipv4",
                        "safi": "unicast",
                        "advertisements": {"matchLabels": {"advertise": "cilium-bgp"}},
                    }
                ]
            },
        }

    def test_advertisement_matches_the_contract(self) -> None:
        """``PodCIDR`` only — advertising Services / LoadBalancer IPs is out of scope."""
        advertisement = _documents(_two_l3_members())[3]

        assert advertisement == {
            "apiVersion": "cilium.io/v2",
            "kind": "CiliumBGPAdvertisement",
            "metadata": {"name": "cilium-bgp-advertisements", "labels": {"advertise": "cilium-bgp"}},
            "spec": {"advertisements": [{"advertisementType": "PodCIDR"}]},
        }

    def test_every_peer_config_ref_resolves_to_the_rendered_peer_config(self) -> None:
        """A dangling ``peerConfigRef`` leaves Cilium with no peering parameters at all."""
        documents = _documents(_two_l3_members())
        peer_config_name = documents[2]["metadata"]["name"]

        referenced = {
            document["spec"]["bgpInstances"][0]["peers"][0]["peerConfigRef"]["name"] for document in documents[:2]
        }

        assert referenced == {peer_config_name}

    def test_advertisement_labels_satisfy_the_peer_config_selector(self) -> None:
        """The peer config selects advertisements by *label*, not by name; both sides are ours.

        A selector that matched nothing would establish the sessions and advertise no routes.
        """
        documents = _documents(_two_l3_members())
        selector = documents[2]["spec"]["families"][0]["advertisements"]["matchLabels"]
        labels = documents[3]["metadata"]["labels"]

        assert selector.items() <= labels.items()


class TestMemberCountDifferencing:
    """Growing or shrinking a cluster by one touches exactly one document (FR-006, US2 scenarios 1 and 2).

    The two renders differ only in their fixture's member count, so any other difference between the
    bodies would be the renderer carrying state it should not.
    """

    def test_adding_a_member_adds_exactly_one_cluster_config(self) -> None:
        """N + 1 members render N + 1 cluster configs — no more, and none merged away."""
        before = _documents(_two_l3_members())
        after = _documents(_three_l3_members())

        added = len(_of_kind(after, "CiliumBGPClusterConfig")) - len(_of_kind(before, "CiliumBGPClusterConfig"))

        assert added == 1

    def test_the_shared_documents_are_byte_identical_across_the_two_renders(self) -> None:
        """The peer config and advertisement are cluster-wide, so member count cannot perturb them.

        Asserted on the parsed documents *and* on their re-serialised text: an operator adding a worker
        must not see the shared half of the manifest re-applied.
        """
        before = _shared_documents(_documents(_two_l3_members()))
        after = _shared_documents(_documents(_three_l3_members()))

        assert before == after
        assert yaml.safe_dump_all(before, sort_keys=False) == yaml.safe_dump_all(after, sort_keys=False)

    def test_removing_a_member_changes_no_other_document(self) -> None:
        """Dropping the added member from the N + 1 body reproduces the N body exactly.

        Whole-document equality is the assertion US2 scenario 2 asks for: it catches both a surviving
        member's document changing and the removed member leaving an orphaned peer behind.
        """
        grown = _documents(_three_l3_members())
        shrunk = _documents(_two_l3_members())

        surviving = [document for document in grown if document["metadata"]["name"] != "cilium-worker-3"]

        assert surviving == shrunk


class TestMemberMove:
    """Re-placing a member on another leaf moves its ``peerAddress`` and nothing else (US2 scenario 3).

    ``peerAddress`` is read from the cabling rather than stored on the session, so it follows a move for
    free — these tests are what pins that down.
    """

    def test_only_the_peer_address_differs_after_a_move(self) -> None:
        """The strongest form of "every other field is unchanged".

        The expected document is the pre-move one with ``peerAddress`` substituted, so ``localASN``,
        ``peerASN``, ``nodeSelector``, ``metadata.name`` and the instance and peer names are all asserted
        unchanged by construction — a move re-places a server, it does not re-number it.
        """
        before = _documents([_member("cilium-worker-1", leaf_address="10.0.0.1/31")])[0]
        after = _documents([_member("cilium-worker-1", leaf_address="10.9.0.7/31")])[0]

        expected = deepcopy(before)
        expected["spec"]["bgpInstances"][0]["peers"][0]["peerAddress"] = "10.9.0.7"

        assert before["spec"]["bgpInstances"][0]["peers"][0]["peerAddress"] == "10.0.0.1"
        assert after == expected

    def test_a_move_leaves_the_shared_documents_untouched(self) -> None:
        """Nothing in the shared half of the manifest derives from where a member is cabled."""
        before = _documents([_member("cilium-worker-1", leaf_address="10.0.0.1/31")])
        after = _documents([_member("cilium-worker-1", leaf_address="10.9.0.7/31")])

        assert _shared_documents(before) == _shared_documents(after)


L2_SELECTOR = "cilium-worker-l2"


def _mixed_members() -> list[dict[str, Any]]:
    """The US3 fixture: two eligible L3 members and one L2 member, the L2 one in the middle.

    Its data is complete apart from ``layer`` — it has a server, an ipv4_unicast session with both
    ASNs and a cabled leaf port — so only the layer check can be what excludes it. It sits between the
    two L3 members and sorts between them by selector, so a filter applied at the wrong point would
    leave a visible gap rather than a trailing one.
    """
    return [
        _member("cilium-worker-1", local_as=4200000001, leaf_address="10.0.0.1/31"),
        _member(L2_SELECTOR, layer="l2", local_as=4200000009, leaf_address="10.0.0.9/31"),
        _member("cilium-worker-2", local_as=4200000002, leaf_address="10.0.0.3/31"),
    ]


class TestMixedCluster:
    """A cluster holding both L2 and L3 members renders only the L3 ones (FR-004, US3 scenario 1)."""

    def test_exactly_two_cluster_configs_are_rendered_for_three_members(self) -> None:
        """One document per *eligible* member — the L2 member is a member but has no peering."""
        documents = _documents(_mixed_members())

        assert len(_of_kind(documents, "CiliumBGPClusterConfig")) == 2

    def test_the_rendered_cluster_configs_are_the_two_l3_members(self) -> None:
        """Named and ordered exactly as the all-L3 fixture would be — the L2 member leaves no gap."""
        documents = _documents(_mixed_members())

        assert [document["metadata"]["name"] for document in _of_kind(documents, "CiliumBGPClusterConfig")] == [
            "cilium-worker-1",
            "cilium-worker-2",
        ]

    def test_the_l2_members_node_selector_appears_nowhere_in_the_body(self) -> None:
        """The strongest form of "appears nowhere": a substring check over the whole rendered text.

        Counting documents cannot catch the L2 member leaking into a *field* of a document that is
        otherwise correctly counted — a ``nodeSelector``, a peer name, a label.
        """
        body = _body(_mixed_members())

        assert L2_SELECTOR not in body

    def test_the_mixed_cluster_renders_exactly_what_the_l3_members_alone_would(self) -> None:
        """Whole-document equality against the two-L3 fixture: the L2 member perturbs nothing.

        Subsumes the count and naming assertions above, and additionally rules out the L2 member
        shifting a surviving member's ASN or address.
        """
        assert _documents(_mixed_members()) == _documents(_two_l3_members())


class TestIncompleteMember:
    """An L3 member still mid-provisioning is dropped; its neighbours are unaffected (US3 scenario 3)."""

    def test_a_member_without_a_stored_session_is_dropped_and_the_complete_one_remains(self) -> None:
        """``local_as=None`` models a session written before the ASN was allocated."""
        members = [
            _member("cilium-worker-1", local_as=4200000001, leaf_address="10.0.0.1/31"),
            _member("cilium-worker-9", local_as=None, leaf_address="10.0.0.9/31"),
        ]

        documents = _documents(members)

        assert [document["metadata"]["name"] for document in _of_kind(documents, "CiliumBGPClusterConfig")] == [
            "cilium-worker-1"
        ]
        assert "cilium-worker-9" not in _body(members)

    def test_a_member_without_a_leaf_address_is_dropped_and_the_complete_one_remains(self) -> None:
        """``leaf_address=None`` models a cabled port whose /31 is not allocated yet."""
        members = [
            _member("cilium-worker-1", local_as=4200000001, leaf_address="10.0.0.1/31"),
            _member("cilium-worker-9", local_as=4200000009, leaf_address=None),
        ]

        documents = _documents(members)

        assert [document["metadata"]["name"] for document in _of_kind(documents, "CiliumBGPClusterConfig")] == [
            "cilium-worker-1"
        ]
        assert "cilium-worker-9" not in _body(members)

    def test_one_complete_member_still_renders_the_full_document_set(self) -> None:
        """The survivor gets its cluster config *and* the shared pair — it is not a degraded render."""
        members = [
            _member("cilium-worker-1", local_as=4200000001, leaf_address="10.0.0.1/31"),
            _member("cilium-worker-9", local_as=None, leaf_address=None),
        ]

        documents = _documents(members)

        assert [document["kind"] for document in documents] == [
            "CiliumBGPClusterConfig",
            "CiliumBGPPeerConfig",
            "CiliumBGPAdvertisement",
        ]


class TestEmptyCluster:
    """No eligible members means **zero** documents — not the shared pair on its own (FR-005, US3 scenario 2).

    Emitting the peer config and advertisement alone would leave a peer config nothing references and
    an advertisement nothing advertises: inert clutter that Vidra would nonetheless apply.
    """

    def test_an_all_l2_cluster_renders_zero_documents(self) -> None:
        members = [
            _member("cilium-worker-l2-a", layer="l2"),
            _member("cilium-worker-l2-b", layer="l2", local_as=4200000002, leaf_address="10.0.0.3/31"),
        ]

        assert _documents(members) == []

    def test_an_all_l2_cluster_does_not_emit_the_shared_documents(self) -> None:
        """Stated separately from the count because it is the specific mistake FR-005 names."""
        members = [_member("cilium-worker-l2-a", layer="l2")]

        assert _shared_documents(_documents(members)) == []

    def test_a_zero_member_cluster_renders_zero_documents(self) -> None:
        assert _documents([]) == []

    def test_a_zero_member_cluster_does_not_emit_the_shared_documents(self) -> None:
        assert _shared_documents(_documents([])) == []

    def test_a_cluster_of_only_incomplete_l3_members_renders_zero_documents(self) -> None:
        """The empty case is about *eligibility*, not about layer — an unprovisioned cluster hits it too."""
        members = [
            _member("cilium-worker-1", local_as=None),
            _member("cilium-worker-2", local_as=4200000002, leaf_address=None),
        ]

        assert _documents(members) == []

    def test_an_empty_render_produces_no_documents_and_raises_nothing(self) -> None:
        """The body itself: whatever text ``safe_dump_all`` produces, it must parse to nothing.

        Asserted through ``safe_load_all`` rather than against ``""`` so the test survives a change in
        how PyYAML renders an empty stream, while still pinning down that Cilium receives no resource.
        """
        assert list(yaml.safe_load_all(_body([]))) == []


# --- Reading the query result --------------------------------------------------------------------
#
# The peering rules decide over `MemberFacts`; turning a GraphQL result into those facts is this
# module's job, so the graph-walking properties are asserted here rather than against the rules.


def _facts(members: list[dict[str, Any]]) -> list[MemberFacts]:
    """Every member's facts, read the way the transform reads them."""
    return cluster_member_facts(CiliumManifestQuery(**_cluster_result(members)))


def _interface(name: str, *, leaf_address: str | None, cabled: bool = True) -> dict[str, Any]:
    """One of a server's ports, optionally cabled to a leaf port holding ``leaf_address``."""
    interface_id = f"interface-{name}"
    link = (
        {
            "node": {
                "id": f"link-{name}",
                "endpoints": {
                    "edges": [
                        {"node": _server_endpoint(interface_id)},
                        {"node": _leaf_endpoint(leaf_address)},
                    ]
                },
            }
        }
        if cabled
        else None
    )
    return {"node": {"id": interface_id, "name": {"value": name}, "link": link}}


def _member_with(
    *,
    sessions: list[dict[str, Any]] | None = None,
    interfaces: list[dict[str, Any]] | None = None,
    name: str = "cilium-worker-1",
) -> dict[str, Any]:
    """A member whose server carries exactly the sessions and ports given."""
    return {
        "node": {
            "id": f"service-{name}",
            "name": {"value": name},
            "layer": {"value": "l3"},
            "server": {
                "node": {
                    "id": f"server-{name}",
                    "hostname": {"value": f"server-{name}"},
                    "node_selector": {"value": name},
                    "asn": {"value": 4200000001},
                    "bgp_sessions": {"edges": sessions if sessions is not None else []},
                    "interfaces": {"edges": interfaces if interfaces is not None else []},
                }
            },
        }
    }


def _session(
    address_family: str, local_as: int | None = 4200000001, remote_as: int | None = OVERLAY_ASN
) -> dict[str, Any]:
    return {
        "node": {
            "id": f"session-{address_family}",
            "address_family": {"value": address_family},
            "local_as": {"value": local_as},
            "remote_as": {"value": remote_as},
        }
    }


class TestSessionSelection:
    """Which of a server's sessions supplies the ASN pair."""

    def test_the_ipv4_unicast_session_is_the_one(self) -> None:
        (facts,) = _facts([_member_with(sessions=[_session("ipv4_unicast", 4200000001, OVERLAY_ASN)])])

        assert facts.session_present
        assert (facts.local_asn, facts.peer_asn) == (4200000001, OVERLAY_ASN)

    def test_a_session_of_another_address_family_does_not_count(self) -> None:
        """An L2VPN-EVPN session belongs to the overlay, and describes no Cilium peering."""
        (facts,) = _facts([_member_with(sessions=[_session("l2vpn_evpn")])])

        assert not facts.session_present
        assert facts.local_asn is None

    def test_the_ipv4_unicast_session_is_found_among_others(self) -> None:
        members = [
            _member_with(sessions=[_session("l2vpn_evpn", 1, 2), _session("ipv4_unicast", 4200000001, OVERLAY_ASN)])
        ]

        (facts,) = _facts(members)

        assert (facts.local_asn, facts.peer_asn) == (4200000001, OVERLAY_ASN)

    def test_a_server_with_no_sessions_reports_none_present(self) -> None:
        (facts,) = _facts([_member_with(sessions=[])])

        assert not facts.session_present

    def test_a_half_written_session_is_present_but_has_no_asn(self) -> None:
        """``session_present`` and the ASNs are separate facts, because they fail different checks."""
        (facts,) = _facts([_member_with(sessions=[_session("ipv4_unicast", None, OVERLAY_ASN)])])

        assert facts.session_present
        assert facts.local_asn is None


class TestLeafAddressSelection:
    """Which cabled port supplies ``peerAddress`` — the within-member half of checksum stability."""

    def test_lowest_named_cabled_interface_wins_regardless_of_query_order(self) -> None:
        """Interfaces are walked in name order, not query order, so the address cannot flip.

        The spec assumes one uplink per member, but a second cabled port (management, or leftovers
        mid-move) would otherwise let ``peerAddress`` alternate between renders.
        """
        low = _interface("eth1", leaf_address="10.0.0.1/31")
        high = _interface("eth2", leaf_address="10.0.0.3/31")

        (forward,) = _facts([_member_with(interfaces=[low, high])])
        (reverse,) = _facts([_member_with(interfaces=[high, low])])

        assert forward.leaf_address == "10.0.0.1/31"
        assert reverse.leaf_address == "10.0.0.1/31"

    def test_an_uncabled_interface_is_skipped_for_the_next_candidate(self) -> None:
        """A lower-named but uncabled port does not shadow the real uplink."""
        members = [
            _member_with(
                interfaces=[
                    _interface("eth0", leaf_address=None, cabled=False),
                    _interface("eth1", leaf_address="10.0.0.1/31"),
                ]
            )
        ]

        (facts,) = _facts(members)

        assert facts.leaf_address == "10.0.0.1/31"

    def test_the_leaf_end_of_the_link_is_taken_never_the_server_end(self) -> None:
        """Both ends hold half of the /31; the server's half is a plausible-looking wrong answer.

        The kind on each endpoint is what discriminates them. The real query selects ``ip_address``
        only ``on NetworkInterface``, so this gives the server end one too — the shape that would
        expose a walker relying on selection rather than on the kind.
        """
        server_end = _server_endpoint("interface-eth1")
        server_end["ip_address"] = {"node": {"id": "server-ip", "address": {"value": "10.0.0.0/31"}}}
        members = [
            _member_with(
                interfaces=[
                    {
                        "node": {
                            "id": "interface-eth1",
                            "name": {"value": "eth1"},
                            "link": {
                                "node": {
                                    "id": "link",
                                    "endpoints": {
                                        "edges": [{"node": server_end}, {"node": _leaf_endpoint("10.0.0.1/31")}]
                                    },
                                }
                            },
                        }
                    }
                ]
            )
        ]

        (facts,) = _facts(members)

        assert facts.leaf_address == "10.0.0.1/31"

    def test_a_server_with_no_interfaces_resolves_no_address(self) -> None:
        (facts,) = _facts([_member_with(interfaces=[])])

        assert facts.leaf_address is None

    def test_a_leaf_port_without_an_ip_resolves_no_address(self) -> None:
        """Cabled, but the /31 is not allocated yet."""
        (facts,) = _facts([_member_with(interfaces=[_interface("eth1", leaf_address=None)])])

        assert facts.leaf_address is None


class TestMemberFactsShape:
    def test_a_member_without_a_server_reports_it_absent(self) -> None:
        """The Server generator has not run yet, so there is nothing else to read."""
        member = {"node": {"id": "service-x", "name": {"value": "x"}, "layer": {"value": "l3"}, "server": None}}

        (facts,) = _facts([member])

        assert facts.name == "x"
        assert not facts.server_present

    def test_the_layer_and_node_selector_pass_through(self) -> None:
        (facts,) = _facts([_member("cilium-worker-1", layer="l2", node_selector="selected")])

        assert facts.layer == "l2"
        assert facts.node_selector == "selected"

    def test_a_cluster_that_matched_nothing_yields_no_facts(self) -> None:
        no_cluster: dict[str, Any] = {"NetworkKubernetesCluster": {"edges": []}}

        assert cluster_member_facts(CiliumManifestQuery(**no_cluster)) == []
