from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from infrahub_sdk.generator import InfrahubGenerator  # type: ignore[import-not-found]
from infrahub_sdk.protocols import CoreIPAddressPool, CoreIPPrefixPool  # type: ignore[import-not-found]

from infrahub_solution_ai_dc.addressing import assign_ip_addresses_to_p2p_connections
from infrahub_solution_ai_dc.cabling import build_pod_cabling_plan, connect_interface_maps
from infrahub_solution_ai_dc.checksum import Checksum
from infrahub_solution_ai_dc.overlay import rr_client, upsert_evpn_session
from infrahub_solution_ai_dc.protocols import LocationRack, NetworkDevice, NetworkFabric, NetworkInterface, NetworkPod
from infrahub_solution_ai_dc.query import only_node, value_of
from infrahub_solution_ai_dc.sorting import interface_ordering
from infrahub_solution_ai_dc.vendors import vendor_group_for_template

from .pod_generator_query import (
    PodGeneratorQuery,
)

if TYPE_CHECKING:
    from infrahub_solution_ai_dc.sorting import InterfaceOrdering

EXCLUDED_POD_ROLES = ["fabric"]


class PodGenerator(InfrahubGenerator):
    pod_id: str
    pod_index: int
    pod_name: str
    pod_spine_switch_template: str | None
    pod_role: str
    vendor_group: str

    fabric_interface_sorting_function: InterfaceOrdering
    spine_interface_sorting_function: InterfaceOrdering

    fabric_id: str
    fabric_name: str

    loopback_pool: CoreIPAddressPool
    vtep_pool: CoreIPAddressPool

    pod_prefix_pool: CoreIPPrefixPool
    server_prefix_pool: CoreIPPrefixPool
    spine_switches: list[NetworkDevice]
    super_spine_switches: list[NetworkDevice]
    spine_super_spine_ids: dict[str, set[str]]

    logger = logging.getLogger("infrahub.tasks")

    async def generate(self, data: dict) -> None:
        parsed = PodGeneratorQuery(**data)
        pod = only_node(parsed.network_pod.edges, of="the pod this generator was dispatched for")

        self.pod_id = pod.id
        label = f"pod {pod.id}"
        self.pod_index = value_of(pod.index, field="index", of=label)
        self.pod_name = value_of(pod.name, field="name", of=label).lower()
        self.pod_role = value_of(pod.role, field="role", of=label)
        # Optional on purpose: a pod with no spine template is reported below, after the role filter,
        # so an unmanaged pod is skipped rather than rejected.
        template = pod.spine_switch_template.node if pod.spine_switch_template else None
        self.pod_spine_switch_template = template.id if template else None
        self.amount_of_spines = value_of(pod.amount_of_spines, field="amount_of_spines", of=label)

        # ``parent`` is a discriminated union (a building block or a fabric); only a fabric carries the
        # attributes below, and the previous `type: ignore[union-attr]` asserted that silently.
        # Read without the helpers: ``parent`` is a discriminated union (a building block or a
        # fabric) and only the fabric arm carries the attributes below. The previous
        # `type: ignore[union-attr]` asserted that silently; narrowing on the discriminator says it.
        fabric_node = pod.parent.node
        if fabric_node is None:
            msg = f"Cannot read the parent of {label}: the query returned no related node for it"
            raise ValueError(msg)
        if fabric_node.typename__ != "NetworkFabric":
            msg = f"Cannot read the fabric of {label}: its parent is a {fabric_node.typename__}, not a NetworkFabric"
            raise ValueError(msg)
        self.fabric_id = fabric_node.id
        fabric_label = f"fabric of {label}"
        self.fabric_name = value_of(fabric_node.name, field="name", of=fabric_label).lower()
        self.fabric_amount_of_super_spines = value_of(
            fabric_node.amount_of_super_spines, field="amount_of_super_spines", of=fabric_label
        )

        self.spine_switches = []

        if self.pod_role in EXCLUDED_POD_ROLES:
            self.logger.info(
                f"Skipping pod generator on {self.pod_name}-{self.pod_id}: "
                f"role {self.pod_role!r} is not managed by this generator"
            )
            return

        await self.get_super_spine_switches_for_fabric()

        if self.fabric_amount_of_super_spines != len(self.super_spine_switches):
            msg = f"Cannot start pod generator on {self.pod_name}-{self.pod_id}: the fabric doesn't seem to be fully generated yet!"
            raise RuntimeError(msg)

        if not self.pod_spine_switch_template:
            msg = f"Cannot start pod generator on {self.pod_name}-{self.pod_id}: no spine switch template defined!"
            raise RuntimeError(msg)

        fabric = f"fabric {self.fabric_name}-{self.fabric_id}"
        self.fabric_interface_sorting_function = interface_ordering(
            fabric_node.fabric_interface_sorting_method.value if fabric_node.fabric_interface_sorting_method else None,
            design_object=fabric,
        )
        self.spine_interface_sorting_function = interface_ordering(
            fabric_node.spine_interface_sorting_method.value if fabric_node.spine_interface_sorting_method else None,
            design_object=fabric,
        )

        self.vendor_group = await vendor_group_for_template(self.client, self.pod_spine_switch_template)

        await self.allocate_resource_pools()

        await self.create_spine_switches()

        await self.connect_spine_to_super_spine()

        await self.update_checksum()

        # Stamp the overlay ASN on the spines after the checksum so it never re-triggers the rack cascade.
        await self.configure_overlay()

    async def create_spine_switches(self) -> None:
        """Create the spine switches"""

        for idx in range(1, self.amount_of_spines + 1):
            device = await self.client.create(
                NetworkDevice,
                hostname=f"spine-{self.pod_name}-{idx}",
                object_template={"id": self.pod_spine_switch_template},
                pod={"id": self.pod_id},
                loopback_ip=self.loopback_pool,
                role="spine",
                member_of_groups=["devices", self.vendor_group],
            )
            await device.save(allow_upsert=True)

            # FIX: seems the id of a related node assigned from a pool is not immediately accessible
            device = await self.client.get(
                NetworkDevice,
                id=device.id,
                include=["ip_address"],
                exclude=["rack", "pod", "role", "hostname", "object_template", "member_of_groups"],
            )
            loopback_interface = await self.client.get(
                NetworkInterface, device__ids=[device.id], role__value="loopback"
            )
            loopback_interface.status.value = "active"
            loopback_interface.ip_address = device.loopback_ip.id  # type: ignore[assignment]
            await loopback_interface.save(allow_upsert=True)

            self.spine_switches.append(device)

    async def allocate_resource_pools(self) -> None:
        """Allocate IP Space for the Pod"""

        fabric_prefix_pool = await self.client.get(CoreIPPrefixPool, name__value=f"{self.fabric_name}-prefix-pool")

        pod_supernet = await self.client.allocate_next_ip_prefix(
            resource_pool=fabric_prefix_pool,
            identifier=self.pod_id,
            member_type="prefix",
            prefix_length=19,
            data={"role": "pod_supernet"},
        )

        self.pod_prefix_pool = await self.client.create(
            kind=CoreIPPrefixPool,
            name=f"{self.fabric_name}-{self.pod_name}-prefix-pool",
            default_prefix_type="IpamIPPrefix",
            default_prefix_length=24,
            ip_namespace={"hfid": ["default"]},
            resources=[pod_supernet],
        )
        await self.pod_prefix_pool.save(allow_upsert=True)

        pod_loopback_prefix = await self.client.allocate_next_ip_prefix(
            resource_pool=self.pod_prefix_pool,
            identifier=str(self.pod_id),
            member_type="address",
            prefix_length=27,
            data={"role": "pod_loopback"},
        )

        self.loopback_pool = await self.client.create(
            kind=CoreIPAddressPool,
            name=f"{self.fabric_name}-{self.pod_name}-loopback-pool",
            default_address_type="IpamIPAddress",
            default_prefix_length=32,
            ip_namespace={"hfid": ["default"]},
            resources=[pod_loopback_prefix],
        )
        await self.loopback_pool.save(allow_upsert=True)

        # Dedicated per-pod VTEP loopback (loopback1) pool — NVE source on leafs (mirrors loopback_pool).
        pod_vtep_prefix = await self.client.allocate_next_ip_prefix(
            resource_pool=self.pod_prefix_pool,
            identifier=f"{self.pod_id}-vtep",
            member_type="address",
            prefix_length=27,
            data={"role": "pod_vtep_loopback"},
        )

        self.vtep_pool = await self.client.create(
            kind=CoreIPAddressPool,
            name=f"{self.fabric_name}-{self.pod_name}-vtep-pool",
            default_address_type="IpamIPAddress",
            default_prefix_length=32,
            ip_namespace={"hfid": ["default"]},
            resources=[pod_vtep_prefix],
        )
        await self.vtep_pool.save(allow_upsert=True)

        # Per-pod server /31 pool: carve a /24 from the global ServerSupernetPool (192.168.0.0/16,
        # seeded in objects/04_ipam.yml) and hand out /31s for server<->leaf p2p links. Mirrors the
        # prefix_pool/vtep_pool creation above and stays distinct from the underlay/overlay supernets.
        server_supernet_pool = await self.client.get(CoreIPPrefixPool, name__value="ServerSupernetPool")

        pod_server_supernet = await self.client.allocate_next_ip_prefix(
            resource_pool=server_supernet_pool,
            identifier=f"{self.pod_id}-server",
            member_type="prefix",
            prefix_length=24,
            data={"role": "server_p2p"},
        )

        self.server_prefix_pool = await self.client.create(
            kind=CoreIPPrefixPool,
            name=f"{self.fabric_name}-{self.pod_name}-server-prefix-pool",
            default_prefix_type="IpamIPPrefix",
            default_prefix_length=31,
            ip_namespace={"hfid": ["default"]},
            resources=[pod_server_supernet],
        )
        await self.server_prefix_pool.save(allow_upsert=True)

        pod = await self.client.get(kind=NetworkPod, id=self.pod_id)
        pod.loopback_pool = self.loopback_pool  # type: ignore[assignment]
        pod.prefix_pool = self.pod_prefix_pool  # type: ignore[assignment]
        pod.vtep_pool = self.vtep_pool  # type: ignore[assignment]
        pod.server_prefix_pool = self.server_prefix_pool  # type: ignore[assignment]
        await pod.save(allow_upsert=True)

    async def configure_overlay(self) -> None:
        """Stamp ASN + RR role on every spine and materialize the spine<->super-spine EVPN sessions.

        Spines reflect EVPN routes for their leafs and are themselves clients of the super-spines
        (hierarchical RR, ADR-0005). Sessions follow the cabling recorded in connect_spine_to_super_spine.

        Best-effort: if the FabricGenerator has not allocated overlay_asn yet, skip — the config template falls
        back to the fabric overlay_asn so rendering stays correct regardless of generator timing.
        """
        fabric = await self.client.get(kind=NetworkFabric, id=self.fabric_id)
        overlay_asn = fabric.overlay_asn.value
        if overlay_asn is None:
            self.logger.warning(f"overlay_asn not yet allocated for {self.fabric_name}; skipping spine ASN stamping")
            return

        super_spines_by_id = {ss.id: ss for ss in self.super_spine_switches}
        for spine in self.spine_switches:
            device = await self.client.get(kind=NetworkDevice, id=spine.id)
            if device.asn.value != overlay_asn or not device.route_reflector.value:
                device.asn.value = overlay_asn
                device.route_reflector.value = True
                await device.save(allow_upsert=True)
                self.logger.info(f"Stamped ASN {overlay_asn} (route reflector) on {device.hostname.value}")

            for super_spine_id in sorted(self.spine_super_spine_ids.get(spine.id, set())):
                super_spine = super_spines_by_id[super_spine_id]
                await upsert_evpn_session(
                    self.client,
                    self.logger,
                    device=device,
                    peer=super_spine,
                    asn=overlay_asn,
                    peer_is_rr_client=rr_client("spine", "super_spine"),
                )
                await upsert_evpn_session(
                    self.client,
                    self.logger,
                    device=super_spine,
                    peer=device,
                    asn=overlay_asn,
                    peer_is_rr_client=rr_client("super_spine", "spine"),
                )

    async def get_super_spine_switches_for_fabric(self) -> tuple[NetworkPod, list[NetworkDevice]]:
        self.fabric_pod = await self.client.get(kind=NetworkPod, parent__ids=[self.fabric_id], role__value="fabric")
        self.super_spine_switches = await self.client.filters(
            kind=NetworkDevice, pod__ids=[self.fabric_pod.id], role__value="super_spine"
        )
        return self.fabric_pod, self.super_spine_switches

    async def connect_spine_to_super_spine(self) -> None:
        spine_interfaces = await self.client.filters(
            kind=NetworkInterface, device__ids=[spine.id for spine in self.spine_switches], role__value="super_spine"
        )
        spine_interface_map = self.spine_interface_sorting_function(spine_interfaces)

        super_spine_interfaces = await self.client.filters(
            kind=NetworkInterface, device__ids=[ss.id for ss in self.super_spine_switches], role__value="spine"
        )
        super_spine_interface_map = self.fabric_interface_sorting_function(super_spine_interfaces)

        created_cabling_plan: list[tuple[NetworkInterface, NetworkInterface]] = build_pod_cabling_plan(
            pod_index=self.pod_index,
            src_interface_map=spine_interface_map,
            dst_interface_map=super_spine_interface_map,
        )

        await connect_interface_maps(client=self.client, logger=self.logger, cabling_plan=created_cabling_plan)

        # Remember the spine -> super-spine adjacencies: the EVPN sessions in configure_overlay follow the
        # actual cabling (tiers are not a full mesh).
        self.spine_super_spine_ids = {}
        for src_interface, dst_interface in created_cabling_plan:
            spine_id, super_spine_id = src_interface.device.id, dst_interface.device.id
            if spine_id is not None and super_spine_id is not None:
                self.spine_super_spine_ids.setdefault(spine_id, set()).add(super_spine_id)

        await assign_ip_addresses_to_p2p_connections(
            client=self.client,
            logger=self.logger,
            connections=created_cabling_plan,
            prefix_len=31,
            prefix_role="pod_super_spine_spine",
            pool=self.pod_prefix_pool,
        )

    async def update_checksum(self) -> None:
        """Drive the rack tier: stamp this run's session checksum on every rack of the pod."""
        racks = await self.client.filters(kind=LocationRack, pod__ids=[self.pod_id])
        await Checksum.over_session(self.client).stamp_on(racks, logger=self.logger, track=None)
