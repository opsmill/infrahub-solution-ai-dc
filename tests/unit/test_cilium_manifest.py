"""Tests for the rendered Cilium manifest (transforms/cilium_manifest.py) — US1 unit tests.

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
"""

from __future__ import annotations

from typing import Any

import yaml

from transforms.cilium_manifest import render_cluster_manifest

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


def _documents(members: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Render the manifest for ``members`` and return its parsed documents."""
    return list(yaml.safe_load_all(render_cluster_manifest(_cluster_result(members))))


def _two_l3_members() -> list[dict[str, Any]]:
    """Two eligible L3 members on different leaves — the US1 fixture (N = 2)."""
    return [
        _member("cilium-worker-1", local_as=4200000001, leaf_address="10.0.0.1/31"),
        _member("cilium-worker-2", local_as=4200000002, leaf_address="10.0.0.3/31"),
    ]


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
