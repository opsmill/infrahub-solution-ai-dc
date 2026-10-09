"""Cluster peering rules — which members of a Kubernetes cluster peer, and in what order.

Everything here is **pure and shape-free**: it takes :class:`MemberFacts`, plain values a caller has
already read out of whatever it holds, and returns plain records. It deliberately knows nothing about
how those values were obtained — reading the graph is the caller's job, because the caller is the one
that knows its own response shape (``transforms/cilium_manifest.py`` reads the parsed GraphQL result).
That split is what keeps this module testable with literals instead of node-shaped stubs.

This module owns **eligibility** (``data-model.md`` §5): which members yield a peering at all. It is
the one place in the feature that deliberately does not fail loud — an ineligible member is omitted,
never raised on, so that one mid-provisioning member never withholds valid config from the rest of the
cluster. Omission is silent in the *artifact* but not in the *logs*: pass a ``logger`` and each dropped
member is reported with the check it failed, which is the difference between an invisible failure and
a diagnosable one.

It also owns **ordering across members**: :func:`build_cilium_peerings` sorts by ``node_selector``.
The rendered artifact's checksum is what Vidra compares to decide whether to re-sync, so an unchanged
fabric must render byte-identically. The matching guarantee *within* a member — which of a server's
ports supplies the address — belongs to whoever reads the graph, and is documented there.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, NamedTuple

if TYPE_CHECKING:
    import logging
    from collections.abc import Iterable

#: The address family of the server<->leaf eBGP session the generator writes (``servers.py``).
SERVER_ADDRESS_FAMILY = "ipv4_unicast"

#: The only ``NetworkServerService.layer`` that speaks BGP, and so the only one that peers.
L3_LAYER = "l3"

# Why a member yielded no peering, one string per eligibility check of `data-model.md` §5. Held as
# module constants rather than inline literals so the tests assert the reason an operator will read
# rather than a paraphrase of it.

#: Check 1 — the member is L2, so it has no BGP to express.
OMISSION_NOT_L3 = f"its layer is not {L3_LAYER}"

#: Check 2 — the service resolves to no ``NetworkServer``; the Server generator has not run yet.
OMISSION_NO_SERVER = "it resolves to no server"

#: Check 3 — the server has no session of the address family the generator writes.
OMISSION_NO_SESSION = f"its server has no {SERVER_ADDRESS_FAMILY} BGP session"

#: Check 4 — the session exists but is half-written, so an ASN would have to be invented.
OMISSION_NO_ASN = f"its {SERVER_ADDRESS_FAMILY} BGP session is missing local_as or remote_as"

#: Not one of the five checks, but the same treatment: no selector, nothing to name the document.
OMISSION_NO_NODE_SELECTOR = "its server has no node_selector"

#: Check 5 — nothing cabled, or cabled to a leaf port with no address allocated yet.
OMISSION_NO_LEAF_ADDRESS = "its cabling resolves to no leaf-port address"


@dataclass(frozen=True)
class MemberFacts:
    """What one cluster member's graph yielded — the whole input to the eligibility rules.

    Every field but ``name`` is allowed to be absent, because a member mid-provisioning legitimately
    has nothing there yet, and each absence is a different eligibility check failing. Two of them are
    presence flags rather than values, and both earn their place by distinguishing checks that a bare
    ``None`` could not tell apart: ``server_present`` separates "the Server generator has not run"
    from a server that exists but is incomplete, and ``session_present`` separates "no session yet"
    from a session that exists with an ASN missing.

    ``leaf_address`` is the address **as stored**, prefix length included; stripping it is a Cilium
    concern and happens in :func:`peering_for_member`.
    """

    name: str
    layer: str | None = None
    server_present: bool = False
    session_present: bool = False
    local_asn: int | None = None
    peer_asn: int | None = None
    node_selector: str | None = None
    leaf_address: str | None = None


class CiliumPeering(NamedTuple):
    """One eligible L3 member's peering values, as the Cilium manifest renders them.

    An in-memory record, not an Infrahub node — the intermediate value that keeps selection out of
    the renderer (``data-model.md`` §5), following the ``ProcessedInputData`` convention in
    ``transforms/cabling_plan.py``.

    ``local_asn`` and ``peer_asn`` both come from the member's **server-side** BGP session, so the
    two cannot disagree with the leaf's rendered config. ``peer_address`` is the leaf port's host
    address with no prefix length: Cilium expects ``10.0.0.1``, never ``10.0.0.1/31``.
    """

    node_selector: str
    local_asn: int
    peer_asn: int
    peer_address: str
    instance_name: str


def instance_name(local_asn: int) -> str:
    """Return the BGP instance name for a member, derived from its own ASN.

    Cilium requires the name to be unique within its document only, so deriving it from the member's
    ASN is both sufficient and deterministic.
    """
    return f"instance-{local_asn}"


def strip_prefix_length(address: str) -> str:
    """Return the host part of an interface address — ``10.0.0.1/31`` becomes ``10.0.0.1``.

    Infrahub stores an interface address with its prefix length; Cilium's ``peerAddress`` is a bare
    address and rejects the CIDR form.
    """
    return address.split("/", 1)[0]


def _omitted(facts: MemberFacts, reason: str, logger: logging.Logger | None) -> CiliumPeering | None:
    """Report why a member yields no peering and return ``None`` so the caller drops it.

    Always ``None``; the return type is ``CiliumPeering | None`` only so each eligibility check can be
    written as ``return _omitted(...)``. That form keeps the reason next to the check that knows it, and
    leaves no branch able to log an omission without performing it.
    """
    if logger is not None:
        logger.info(f"Omitting cluster member {facts.name} from the Cilium manifest: {reason}")
    return None


def peering_for_member(facts: MemberFacts, logger: logging.Logger | None = None) -> CiliumPeering | None:
    """Return the ``CiliumPeering`` for one cluster member, or ``None`` when it yields none.

    Applies the five eligibility checks of ``data-model.md`` §5 in order — layer, server, session,
    ASNs, leaf address — plus a null ``node_selector`` guard. An ineligible member is **omitted, never
    raised on** (FR-004/FR-005): one member still mid-provisioning must not withhold valid config from
    the rest of the cluster.

    The layer check comes first because it is the only one that is not about missing data: an L2 member
    can be fully provisioned, with a session and a cabled leaf port, and still must not appear. Its
    server-side session, if any, belongs to the L2 attachment and describes no Cilium peering.

    Pass ``logger`` to have each omission reported with the check it failed; without one the function
    is entirely pure and silent.
    """
    if facts.layer != L3_LAYER:
        return _omitted(facts, OMISSION_NOT_L3, logger)
    if not facts.server_present:
        return _omitted(facts, OMISSION_NO_SERVER, logger)
    if not facts.session_present:
        return _omitted(facts, OMISSION_NO_SESSION, logger)
    if facts.local_asn is None or facts.peer_asn is None:
        return _omitted(facts, OMISSION_NO_ASN, logger)
    if facts.node_selector is None:
        return _omitted(facts, OMISSION_NO_NODE_SELECTOR, logger)
    if facts.leaf_address is None:
        return _omitted(facts, OMISSION_NO_LEAF_ADDRESS, logger)

    return CiliumPeering(
        node_selector=facts.node_selector,
        local_asn=facts.local_asn,
        peer_asn=facts.peer_asn,
        peer_address=strip_prefix_length(facts.leaf_address),
        instance_name=instance_name(facts.local_asn),
    )


def build_cilium_peerings(
    members: Iterable[MemberFacts],
    logger: logging.Logger | None = None,
) -> list[CiliumPeering]:
    """Return the cluster's peering records, ordered by ``node_selector``.

    Members yielding no record are dropped, so an empty cluster — or one whose members are all L2 or
    all mid-provisioning — returns an empty list rather than raising (FR-005).

    ``logger`` is threaded through to :func:`peering_for_member` and affects logging only; the returned
    records, and so the rendered artifact, are identical with and without it.
    """
    peerings = [peering for member in members if (peering := peering_for_member(member, logger)) is not None]
    return sorted(peerings, key=lambda peering: peering.node_selector)
