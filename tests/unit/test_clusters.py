"""Tests for the cluster peering rules (src/infrahub_solution_ai_dc/clusters.py) — US1 and US3 unit tests.

The module decides which cluster members peer and in what order, over ``MemberFacts`` — plain values a
caller has already read out of its own response shape. So everything here is built from literals: there
are no node-shaped stubs, because the rules have no opinion about where the facts came from.

Scope note: this file covers the happy-path field mapping, the across-member ordering the artifact
checksum depends on (US1/US2), and the full eligibility matrix of ``data-model.md`` §5 (US3). Two
neighbouring concerns live elsewhere. *Reading* a member's facts out of a GraphQL result — which
session counts, which end of a link is the leaf, which interface wins — is
tests/unit/test_cilium_manifest.py, since that is where the reading lives. Whether the *rendered body*
leaves an ineligible member out is also there; here it is only whether the record exists.
"""

from __future__ import annotations

import logging
from dataclasses import replace

import pytest

from infrahub_solution_ai_dc.clusters import (
    OMISSION_NO_ASN,
    OMISSION_NO_LEAF_ADDRESS,
    OMISSION_NO_NODE_SELECTOR,
    OMISSION_NO_SERVER,
    OMISSION_NO_SESSION,
    OMISSION_NOT_L3,
    CiliumPeering,
    MemberFacts,
    build_cilium_peerings,
    instance_name,
    strip_prefix_length,
)

OVERLAY_ASN = 65000


def _eligible(
    name: str = "cilium-worker-1",
    *,
    node_selector: str | None = None,
    local_asn: int = 4200000001,
    leaf_address: str = "10.0.0.1/31",
) -> MemberFacts:
    """A fully provisioned L3 member — every eligibility check satisfied."""
    return MemberFacts(
        name=name,
        layer="l3",
        server_present=True,
        session_present=True,
        local_asn=local_asn,
        peer_asn=OVERLAY_ASN,
        node_selector=node_selector if node_selector is not None else name,
        leaf_address=leaf_address,
    )


def _expected(node_selector: str, local_asn: int, peer_address: str) -> CiliumPeering:
    return CiliumPeering(
        node_selector=node_selector,
        local_asn=local_asn,
        peer_asn=OVERLAY_ASN,
        peer_address=peer_address,
        instance_name=f"instance-{local_asn}",
    )


# --- The ineligible members, one per eligibility check of data-model.md §5 -------------------------
#
# Each starts from an eligible member and takes exactly one fact away, so a test that sees it omitted
# has isolated that check. The L2 case in particular keeps every other fact — "L2 but otherwise
# complete" is the only shape that can tell a layer filter apart from the missing-data filters.

INELIGIBLE_CASES: list[tuple[str, MemberFacts, str]] = [
    ("l2-member", replace(_eligible("cilium-worker-l2"), layer="l2"), OMISSION_NOT_L3),
    ("no-server", MemberFacts(name="no-server", layer="l3"), OMISSION_NO_SERVER),
    (
        "no-session",
        MemberFacts(
            name="no-session", layer="l3", server_present=True, node_selector="no-session", leaf_address="10.0.0.11/31"
        ),
        OMISSION_NO_SESSION,
    ),
    (
        "null-local-as",
        MemberFacts(
            name="null-local-as",
            layer="l3",
            server_present=True,
            session_present=True,
            local_asn=None,
            peer_asn=OVERLAY_ASN,
            node_selector="null-local-as",
            leaf_address="10.0.0.15/31",
        ),
        OMISSION_NO_ASN,
    ),
    (
        "null-remote-as",
        MemberFacts(
            name="null-remote-as",
            layer="l3",
            server_present=True,
            session_present=True,
            local_asn=4200000017,
            peer_asn=None,
            node_selector="null-remote-as",
            leaf_address="10.0.0.17/31",
        ),
        OMISSION_NO_ASN,
    ),
    (
        "no-node-selector",
        MemberFacts(
            name="no-node-selector",
            layer="l3",
            server_present=True,
            session_present=True,
            local_asn=4200000019,
            peer_asn=OVERLAY_ASN,
            node_selector=None,
            leaf_address="10.0.0.19/31",
        ),
        OMISSION_NO_NODE_SELECTOR,
    ),
    (
        "no-leaf-address",
        MemberFacts(
            name="no-leaf-address",
            layer="l3",
            server_present=True,
            session_present=True,
            local_asn=4200000021,
            peer_asn=OVERLAY_ASN,
            node_selector="no-leaf-address",
            leaf_address=None,
        ),
        OMISSION_NO_LEAF_ADDRESS,
    ),
]

INELIGIBLE_MEMBERS = [pytest.param(facts, reason, id=case_id) for case_id, facts, reason in INELIGIBLE_CASES]
INELIGIBLE_FACTS = [pytest.param(facts, id=case_id) for case_id, facts, _ in INELIGIBLE_CASES]


class TestBuildCiliumPeerings:
    """Eligible members -> records whose every field comes from the facts they were given."""

    def test_two_eligible_members_yield_two_mapped_records(self) -> None:
        """Each field maps per data-model.md §5: ASNs from the server-side session, address from cabling."""
        members = [
            _eligible("cilium-worker-1", local_asn=4200000001, leaf_address="10.0.0.1/31"),
            _eligible("cilium-worker-2", local_asn=4200000002, leaf_address="10.0.0.3/31"),
        ]

        assert build_cilium_peerings(members) == [
            _expected("cilium-worker-1", 4200000001, "10.0.0.1"),
            _expected("cilium-worker-2", 4200000002, "10.0.0.3"),
        ]

    def test_local_and_peer_asn_are_never_swapped(self) -> None:
        """``local_as`` is the member's own ASN and ``remote_as`` the leaf's (SC-002)."""
        (peering,) = build_cilium_peerings([_eligible(local_asn=4200000001)])

        assert peering.local_asn == 4200000001
        assert peering.peer_asn == OVERLAY_ASN

    def test_peer_address_has_its_prefix_length_stripped(self) -> None:
        """Cilium wants a bare host address, never the stored CIDR form."""
        (peering,) = build_cilium_peerings([_eligible(leaf_address="10.0.0.1/31")])

        assert peering.peer_address == "10.0.0.1"

    def test_the_node_selector_is_used_not_the_service_name(self) -> None:
        """The record's selector is the Server's computed ``node_selector``, not the service name."""
        (peering,) = build_cilium_peerings([_eligible("some-other-service-name", node_selector="cilium-worker-1")])

        assert peering.node_selector == "cilium-worker-1"

    def test_records_are_sorted_by_node_selector(self) -> None:
        """Across-member ordering is by ``node_selector`` regardless of fetch order (FR-008).

        Without this the artifact checksum changes on every render and Vidra re-syncs forever.
        """
        members = [_eligible("cilium-worker-3"), _eligible("cilium-worker-1"), _eligible("cilium-worker-2")]

        assert [peering.node_selector for peering in build_cilium_peerings(members)] == [
            "cilium-worker-1",
            "cilium-worker-2",
            "cilium-worker-3",
        ]

    def test_shuffled_input_order_yields_identical_records(self) -> None:
        """The *whole* record list is invariant under input order, not just its ``node_selector`` column.

        Sorting by selector is only half of checksum stability: if any other field were carried over
        from a neighbouring member, the artifact would still be ordered and still churn. Reversal plus
        one rotation covers both a full flip and an off-by-one shift, and both are deterministic — a
        randomised shuffle here could pass on a lucky permutation.
        """
        members = [
            _eligible("cilium-worker-1", local_asn=4200000001, leaf_address="10.0.0.1/31"),
            _eligible("cilium-worker-2", local_asn=4200000002, leaf_address="10.0.0.3/31"),
            _eligible("cilium-worker-3", local_asn=4200000003, leaf_address="10.0.0.5/31"),
        ]

        expected = build_cilium_peerings(members)

        assert build_cilium_peerings(list(reversed(members))) == expected
        assert build_cilium_peerings([*members[1:], members[0]]) == expected

    def test_no_members_yields_no_records(self) -> None:
        """A zero-member cluster is valid and produces nothing to render (FR-005)."""
        assert build_cilium_peerings([]) == []


class TestStripPrefixLength:
    def test_prefix_length_is_removed(self) -> None:
        """``peerAddress`` is a bare host address — ``10.0.0.1``, never ``10.0.0.1/31``."""
        assert strip_prefix_length("10.0.0.1/31") == "10.0.0.1"

    def test_a_bare_address_is_unchanged(self) -> None:
        """An address stored without a prefix length passes through untouched."""
        assert strip_prefix_length("10.0.0.1") == "10.0.0.1"


class TestInstanceName:
    def test_instance_name_is_derived_from_the_local_asn(self) -> None:
        """Deterministic and unique within the document, which is all Cilium requires."""
        assert instance_name(4200000001) == "instance-4200000001"


class TestEligibility:
    """The full exclusion matrix of data-model.md §5 (FR-004, FR-005, US3).

    Every case is a member that must be dropped and must not raise. The two properties are asserted
    separately on purpose: a filter that raised would also produce no record, so "omitted" alone
    cannot tell an omission apart from a failure that took the whole cluster's artifact with it.
    """

    @pytest.mark.parametrize("facts", INELIGIBLE_FACTS)
    def test_an_ineligible_member_yields_no_record(self, facts: MemberFacts) -> None:
        """Each failed check omits the member — and only that member."""
        assert build_cilium_peerings([facts]) == []

    @pytest.mark.parametrize("facts", INELIGIBLE_FACTS)
    def test_an_ineligible_member_does_not_suppress_an_eligible_one(self, facts: MemberFacts) -> None:
        """The reason omission beats raising: one mid-provisioning member must not withhold the rest.

        Asserting the surviving record in full also rules out the ineligible member leaking a field
        into its neighbour.
        """
        assert build_cilium_peerings([facts, _eligible()]) == [_expected("cilium-worker-1", 4200000001, "10.0.0.1")]

    def test_a_cluster_of_only_ineligible_members_yields_no_records_and_no_error(self) -> None:
        """The all-L2 / all-incomplete cluster: an empty list, never an exception (FR-005)."""
        assert build_cilium_peerings([facts for _, facts, _ in INELIGIBLE_CASES]) == []

    def test_an_l2_member_is_dropped_even_though_its_data_is_complete(self) -> None:
        """The layer check is load-bearing on its own, not a by-product of missing data (FR-004).

        This member carries a complete session, an ASN pair and a leaf address, so every other check
        passes and only ``layer`` can be what excludes it.
        """
        complete_l2 = MemberFacts(
            name="cilium-worker-l2",
            layer="l2",
            server_present=True,
            session_present=True,
            local_asn=4200000009,
            peer_asn=OVERLAY_ASN,
            node_selector="cilium-worker-l2",
            leaf_address="10.0.0.9/31",
        )

        assert build_cilium_peerings([complete_l2]) == []


class TestOmissionLogging:
    """An omission is silent in the artifact but never in the logs."""

    @pytest.mark.parametrize(("facts", "expected_reason"), INELIGIBLE_MEMBERS)
    def test_each_omission_reports_the_check_it_failed(
        self, facts: MemberFacts, expected_reason: str, caplog: pytest.LogCaptureFixture
    ) -> None:
        logger = logging.getLogger("test.clusters")

        with caplog.at_level(logging.INFO, logger="test.clusters"):
            build_cilium_peerings([facts], logger=logger)

        assert len(caplog.records) == 1
        assert expected_reason in caplog.records[0].message

    def test_the_omission_names_the_member(self, caplog: pytest.LogCaptureFixture) -> None:
        """The service name is the handle back to the object the operator declared."""
        logger = logging.getLogger("test.clusters")

        with caplog.at_level(logging.INFO, logger="test.clusters"):
            build_cilium_peerings([MemberFacts(name="no-server", layer="l3")], logger=logger)

        assert "no-server" in caplog.records[0].message

    def test_an_eligible_member_logs_nothing(self, caplog: pytest.LogCaptureFixture) -> None:
        logger = logging.getLogger("test.clusters")

        with caplog.at_level(logging.INFO, logger="test.clusters"):
            build_cilium_peerings([_eligible()], logger=logger)

        assert caplog.records == []

    def test_logging_does_not_change_the_records(self, caplog: pytest.LogCaptureFixture) -> None:
        """``logger`` affects logging only — the artifact is identical with and without it."""
        members = [_eligible("cilium-worker-1"), MemberFacts(name="no-server", layer="l3")]
        logger = logging.getLogger("test.clusters")

        with caplog.at_level(logging.INFO, logger="test.clusters"):
            with_logger = build_cilium_peerings(members, logger=logger)

        assert with_logger == build_cilium_peerings(members)
