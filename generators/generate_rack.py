from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Protocol

from infrahub_sdk.generator import InfrahubGenerator  # type: ignore[import-not-found]
from infrahub_sdk.protocols import CoreIPAddressPool, CoreIPPrefixPool  # type: ignore[import-not-found]

from infrahub_solution_ai_dc.addressing import (
    assign_ip_addresses_to_p2p_connections,
    assign_vtep_loopback_to_device,
)
from infrahub_solution_ai_dc.cabling import build_rack_cabling_plan, connect_interface_maps
from infrahub_solution_ai_dc.overlay import rr_client, upsert_evpn_session
from infrahub_solution_ai_dc.protocols import NetworkDevice, NetworkFabric, NetworkInterface, NetworkPod
from infrahub_solution_ai_dc.query import only_node, related, related_id, value_of
from infrahub_solution_ai_dc.sorting import interface_ordering
from infrahub_solution_ai_dc.vendors import vendor_group_for_template

from .rack_generator_query import RackGeneratorQuery

if TYPE_CHECKING:
    from infrahub_solution_ai_dc.sorting import InterfaceOrdering

EXCLUDED_RACK_TYPES: list[str] = []


class _HasId(Protocol):
    """Structural view of a pool node — only its ``id`` matters here.

    Declared read-only (a property, not an attribute) so the protocol is covariant: a mutable
    attribute would be invariant, and no concrete node type would satisfy it.
    """

    @property
    def id(self) -> str | None: ...


class _PoolRelationship(Protocol):
    """Structural view of a to-one pool relationship on the pod, as the generator query returns it."""

    @property
    def node(self) -> _HasId | None: ...


def require_pod_pool(
    pool: _PoolRelationship | None,
    *,
    pool_name: str,
    rack: str,
    pod: str,
) -> str:
    """Return the id of the pod's ``pool_name``, or fail loud naming what is not ready yet.

    A rack's leaf switches draw their loopback address and their leaf<->spine /31s from pools the
    **PodGenerator** allocates on the pod. A rack whose pod has not finished generating therefore
    arrives here with the relationship unset, and dereferencing it straight through died with
    ``AttributeError: 'NoneType' object has no attribute 'id'`` — naming neither the rack, the pod,
    nor the pool.

    Unlike the pod's ``vtep_pool`` (best-effort, see :meth:`RackGenerator.configure_overlay`) these
    two cannot be skipped: without them there is no address to give a leaf, so this raises rather
    than warning. ``RuntimeError`` matches the sibling "the pod doesn't seem to be fully generated"
    check in :meth:`RackGenerator.generate` — both mean the cascade above this rack is incomplete.
    """
    node = pool.node if pool is not None else None
    pool_id = node.id if node is not None else None
    if pool_id is None:
        msg = (
            f"Cannot run rack generator on {rack}: pod {pod} has no {pool_name} allocated yet. "
            f"The PodGenerator allocates it — let {pod} finish generating, then re-run this rack."
        )
        raise RuntimeError(msg)
    return pool_id


class RackGenerator(InfrahubGenerator):
    rack_id: str
    rack_index: int
    rack_name: str
    rack_leaf_switch_template: str
    rack_amount_of_leafs: int
    vendor_group: str

    spine_interface_sorting_function: InterfaceOrdering
    leaf_interface_sorting_function: InterfaceOrdering

    pod_id: str
    pod_index: int
    pod_name: str

    spine_switches: list[NetworkDevice]

    leaf_switches: list[NetworkDevice]
    leaf_spine_ids: dict[str, set[str]]

    loopback_pool: CoreIPAddressPool
    prefix_pool: CoreIPPrefixPool

    logger = logging.getLogger("infrahub.tasks")

    async def generate(self, data: dict) -> None:
        parsed = RackGeneratorQuery(**data)
        rack = only_node(parsed.location_rack.edges, of="the rack this generator was dispatched for")

        self.rack_id = rack.id
        label = f"rack {rack.id}"
        self.rack_index = value_of(rack.index, field="index", of=label)
        self.rack_name = value_of(rack.name, field="name", of=label)
        self.rack_type = value_of(rack.rack_type, field="rack_type", of=label)
        self.rack_leaf_switch_template = related_id(rack.leaf_switch_template, field="leaf_switch_template", of=label)
        self.rack_amount_of_leafs = value_of(rack.amount_of_leafs, field="amount_of_leafs", of=label)
        self.leaf_switches = []

        self.vendor_group = await vendor_group_for_template(self.client, self.rack_leaf_switch_template)

        pod_node = related(rack.pod, field="pod", of=label)
        pod_label = f"pod of {label}"
        self.pod_id = related_id(rack.pod, field="pod", of=label)
        self.pod_index = value_of(pod_node.index, field="index", of=pod_label)
        self.pod_name = value_of(pod_node.name, field="name", of=pod_label).lower()
        self.pod_amount_of_spines = value_of(pod_node.amount_of_spines, field="amount_of_spines", of=pod_label)

        # Guarded rather than dereferenced straight through: both pools are allocated by the
        # PodGenerator, so a rack whose pod is still mid-cascade arrives here with them unset.
        self.loopback_pool_id: str = require_pod_pool(
            pod_node.loopback_pool,
            pool_name="loopback_pool",
            rack=f"{self.rack_name}-{self.rack_id}",
            pod=self.pod_name,
        )
        self.prefix_pool_id: str = require_pod_pool(
            pod_node.prefix_pool,
            pool_name="prefix_pool",
            rack=f"{self.rack_name}-{self.rack_id}",
            pod=self.pod_name,
        )

        self.loopback_pool = await self.client.get(kind=CoreIPAddressPool, id=self.loopback_pool_id)
        self.prefix_pool = await self.client.get(kind=CoreIPPrefixPool, id=self.prefix_pool_id)

        self.spine_switches = await self.client.filters(kind=NetworkDevice, pod__ids=[self.pod_id], role__value="spine")

        if self.rack_type in EXCLUDED_RACK_TYPES:
            msg = f"Cannot run rack generator on {self.rack_name}-{self.rack_id}: {self.rack_type} is not supported by the generator!"
            raise ValueError(msg)

        if self.pod_amount_of_spines != len(self.spine_switches):
            msg = f"Cannot start rack generator on {self.rack_name}-{self.rack_id}: the pod doesn't seem to be fully generated"
            raise RuntimeError(msg)

        pod = f"pod {self.pod_name}-{self.pod_id}"
        self.leaf_interface_sorting_function = interface_ordering(
            pod_node.leaf_interface_sorting_method.value if pod_node.leaf_interface_sorting_method else None,
            design_object=pod,
        )
        self.spine_interface_sorting_function = interface_ordering(
            pod_node.spine_interface_sorting_method.value if pod_node.spine_interface_sorting_method else None,
            design_object=pod,
        )

        await self.create_leaf_switches()

        await self.connect_leafs_to_spine()

        await self.configure_overlay()

    async def configure_overlay(self) -> None:
        """Give each leaf its VTEP loopback (loopback1 from the per-pod VTEP pool) and stamp the overlay ASN.

        ASN stamping is best-effort: if the FabricGenerator has not allocated overlay_asn yet, skip it — the
        config template falls back to the fabric overlay_asn so rendering stays correct regardless of timing.
        """
        pod = await self.client.get(kind=NetworkPod, id=self.pod_id, include=["parent", "vtep_pool"])

        if pod.vtep_pool.id is not None:
            vtep_pool = await self.client.get(kind=CoreIPAddressPool, id=pod.vtep_pool.id)
            for leaf in self.leaf_switches:
                await assign_vtep_loopback_to_device(
                    client=self.client, logger=self.logger, device=leaf, vtep_pool=vtep_pool
                )
        else:
            self.logger.warning(f"Pod {self.pod_name} has no vtep_pool; skipping VTEP loopback assignment")

        fabric = await self.client.get(kind=NetworkFabric, id=pod.parent.id)
        overlay_asn = fabric.overlay_asn.value
        if overlay_asn is None:
            self.logger.warning(f"overlay_asn not yet allocated for pod {self.pod_name}; skipping leaf ASN stamping")
            return

        spines_by_id = {spine.id: spine for spine in self.spine_switches}
        for leaf in self.leaf_switches:
            device = await self.client.get(kind=NetworkDevice, id=leaf.id)
            if device.asn.value != overlay_asn:
                device.asn.value = overlay_asn
                await device.save(allow_upsert=True)
                self.logger.info(f"Stamped ASN {overlay_asn} on {device.hostname.value}")

            # Materialize the leaf<->spine EVPN sessions along the cabling: the leaf is an RR client of its
            # spines; the spines reflect for the leaf (hierarchical RR, ADR-0005).
            for spine_id in sorted(self.leaf_spine_ids.get(leaf.id, set())):
                spine = spines_by_id[spine_id]
                await upsert_evpn_session(
                    self.client,
                    self.logger,
                    device=device,
                    peer=spine,
                    asn=overlay_asn,
                    peer_is_rr_client=rr_client("leaf", "spine"),
                )
                await upsert_evpn_session(
                    self.client,
                    self.logger,
                    device=spine,
                    peer=device,
                    asn=overlay_asn,
                    peer_is_rr_client=rr_client("spine", "leaf"),
                )

    async def create_leaf_switches(self) -> None:
        for index in range(1, self.rack_amount_of_leafs + 1):
            leaf_switch = await self.client.create(
                NetworkDevice,
                hostname=f"leaf-{self.pod_name}-{self.rack_index}-{index}",
                object_template={"id": self.rack_leaf_switch_template},
                pod={"id": self.pod_id},
                rack={"id": self.rack_id},
                loopback_ip=self.loopback_pool,
                index=index,
                role="leaf",
                member_of_groups=["devices", self.vendor_group],
            )
            await leaf_switch.save(allow_upsert=True)
            self.leaf_switches.append(leaf_switch)

            # FIX: seems the id of a related node assigned from a pool is not immediately accessible
            device = await self.client.get(
                NetworkDevice,
                id=leaf_switch.id,
                include=["ip_address"],
                exclude=["rack", "pod", "role", "hostname", "object_template", "member_of_groups"],
            )
            loopback_interface = await self.client.get(
                NetworkInterface, device__ids=[device.id], role__value="loopback"
            )
            loopback_interface.status.value = "active"
            loopback_interface.ip_address = device.loopback_ip.id  # type: ignore[assignment]
            await loopback_interface.save(allow_upsert=True)

    async def connect_leafs_to_spine(self) -> None:
        spine_interfaces = await self.client.filters(
            kind=NetworkInterface, device__ids=[spine.id for spine in self.spine_switches], role__value="leaf"
        )
        spine_interface_map = self.spine_interface_sorting_function(spine_interfaces)

        leaf_interfaces = await self.client.filters(
            kind=NetworkInterface,
            device__ids=[leaf_switch.id for leaf_switch in self.leaf_switches],
            role__value="spine",
        )
        leaf_interface_map = self.leaf_interface_sorting_function(leaf_interfaces)

        created_cabling_plan: list[tuple[NetworkInterface, NetworkInterface]] = build_rack_cabling_plan(
            rack_index=self.rack_index,
            src_interface_map=leaf_interface_map,
            dst_interface_map=spine_interface_map,
        )

        await connect_interface_maps(client=self.client, logger=self.logger, cabling_plan=created_cabling_plan)

        # Remember the leaf -> spine adjacencies: the EVPN sessions in configure_overlay follow the
        # actual cabling (tiers are not a full mesh).
        self.leaf_spine_ids = {}
        for src_interface, dst_interface in created_cabling_plan:
            leaf_id, spine_id = src_interface.device.id, dst_interface.device.id
            if leaf_id is not None and spine_id is not None:
                self.leaf_spine_ids.setdefault(leaf_id, set()).add(spine_id)

        await assign_ip_addresses_to_p2p_connections(
            client=self.client,
            logger=self.logger,
            connections=created_cabling_plan,
            prefix_len=31,
            prefix_role="pod_leaf_spine",
            pool=self.prefix_pool,
        )
