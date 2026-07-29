"""Tests for vendor-group resolution (src/infrahub_solution_ai_dc/vendors.py)."""

from __future__ import annotations

import pytest

from infrahub_solution_ai_dc.vendors import SUPPORTED_VENDORS, vendor_group_for_manufacturer


class TestVendorGroupForManufacturer:
    @pytest.mark.parametrize(
        ("manufacturer", "expected"),
        [
            ("Cisco", "cisco_devices"),
            ("Arista", "arista_devices"),
            ("Dell", "dell_devices"),
            ("Juniper", "juniper_devices"),
            ("  DELL  ", "dell_devices"),  # trimmed + case-insensitive
        ],
    )
    def test_supported_manufacturers_map_to_groups(self, manufacturer: str, expected: str) -> None:
        assert vendor_group_for_manufacturer(manufacturer, device_label="leaf-1") == expected

    def test_every_supported_vendor_resolves(self) -> None:
        for vendor in SUPPORTED_VENDORS:
            assert vendor_group_for_manufacturer(vendor, device_label="d") == f"{vendor}_devices"

    @pytest.mark.parametrize("missing", [None, "", "   "])
    def test_missing_manufacturer_raises_naming_device(self, missing: str | None) -> None:
        with pytest.raises(ValueError, match="leaf-1"):
            vendor_group_for_manufacturer(missing, device_label="leaf-1")

    def test_unsupported_manufacturer_raises_naming_device(self) -> None:
        with pytest.raises(ValueError, match="leaf-1") as exc:
            vendor_group_for_manufacturer("Nokia", device_label="leaf-1")
        assert "Nokia" in str(exc.value)
