"""Vendor resolution for per-vendor device grouping.

Every device is built from an object template that carries a ``device_type`` and therefore a
manufacturer. This module maps that manufacturer to the vendor device group the device belongs
to (``cisco_devices`` / ``arista_devices`` / ``dell_devices``). Resolution is fail-loud: an
unresolvable or unsupported manufacturer raises, so data gaps surface instead of silently
dropping a device's config (spec FR-004 / SC-004).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from infrahub_solution_ai_dc.protocols import (  # type: ignore[import-not-found]
    NetworkDeviceType,
    OrganizationManufacturer,
    TemplateNetworkDevice,
)

if TYPE_CHECKING:
    from infrahub_sdk import InfrahubClient  # type: ignore[import-not-found]

# Manufacturers that have both a vendor device group and a per-vendor config template.
SUPPORTED_VENDORS: tuple[str, ...] = ("cisco", "arista", "dell")


def vendor_group_for_manufacturer(manufacturer_name: str | None, *, device_label: str) -> str:
    """Map a manufacturer name to its vendor device-group name.

    Returns ``f"{vendor}_devices"`` for a supported manufacturer. Raises ``ValueError`` naming
    the offending object when the manufacturer is missing or unsupported (fail-loudly).
    """
    if not manufacturer_name or not manufacturer_name.strip():
        msg = f"Cannot resolve a vendor group for {device_label}: no manufacturer on its device type"
        raise ValueError(msg)

    vendor = manufacturer_name.strip().lower()
    if vendor not in SUPPORTED_VENDORS:
        msg = (
            f"Cannot resolve a vendor group for {device_label}: manufacturer {manufacturer_name!r} "
            f"has no vendor group (supported: {', '.join(SUPPORTED_VENDORS)})"
        )
        raise ValueError(msg)

    return f"{vendor}_devices"


async def vendor_group_for_template(client: InfrahubClient, template_id: str) -> str:
    """Resolve the vendor device-group name for a device object template.

    Reads ``TemplateNetworkDevice.device_type`` → ``NetworkDeviceType.manufacturer`` →
    ``OrganizationManufacturer.name`` and maps it via :func:`vendor_group_for_manufacturer`.
    All devices built from a template share its manufacturer, so a generator resolves this once
    and passes it to ``member_of_groups`` at device-creation time.
    """
    label = f"template {template_id}"

    template = await client.get(kind=TemplateNetworkDevice, id=template_id, include=["device_type"])
    device_type_rel = template.device_type
    if device_type_rel is None or device_type_rel.id is None:
        return vendor_group_for_manufacturer(None, device_label=label)

    device_type = await client.get(kind=NetworkDeviceType, id=device_type_rel.id, include=["manufacturer"])
    manufacturer_rel = device_type.manufacturer
    if manufacturer_rel is None or manufacturer_rel.id is None:
        return vendor_group_for_manufacturer(None, device_label=label)

    manufacturer = await client.get(kind=OrganizationManufacturer, id=manufacturer_rel.id)
    return vendor_group_for_manufacturer(manufacturer.name.value, device_label=label)  # type: ignore[union-attr]
