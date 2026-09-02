"""Guards the eight Cumulus device templates against a copy-paste/wiring error (research.md D10).

Eight near-identical `TemplateNetworkDevice` entries in `objects/06_device_template.yml` are meant
to differ only in `template_name` and `device_type`. This reads that file as plain YAML data (it is
never imported as Python) and asserts, for each one, that its `device_type` points at the intended
Spectrum-ASIC-generation/role pairing and that its declared interface-name ranges expand (via the
same `range_expansion` helper Infrahub itself uses at load time) to the expected interface count and
first/last name.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from infrahub_sdk.spec.range_expansion import range_expansion  # type: ignore[import-not-found]

REPO_ROOT = Path(__file__).resolve().parents[2]
DEVICE_TEMPLATE_FILE = REPO_ROOT / "objects" / "06_device_template.yml"

# template_name -> (device_type, [(interface name pattern, expected count, first name, last name,
# expected profiles or None for the loopback), ...])
EXPECTED_TEMPLATES: dict[str, tuple[list[str], list[tuple[str, int, str, str, list[str] | None]]]] = {
    "cumulus-spectrum2-super-spine-switch": (
        ["Cumulus", "Cumulus-SPECTRUM2"],
        [
            ("Loopback0", 1, "Loopback0", "Loopback0", None),
            ("swp[1-64]", 64, "swp1", "swp64", ["profile-interface-spine"]),
        ],
    ),
    "cumulus-spectrum2-spine-switch": (
        ["Cumulus", "Cumulus-SPECTRUM2"],
        [
            ("Loopback0", 1, "Loopback0", "Loopback0", None),
            ("swp[1-32]", 32, "swp1", "swp32", ["profile-interface-leaf"]),
            ("swp[33-64]", 32, "swp33", "swp64", ["profile-interface-super-spine"]),
        ],
    ),
    "cumulus-spectrum3-super-spine-switch": (
        ["Cumulus", "Cumulus-SPECTRUM3"],
        [
            ("Loopback0", 1, "Loopback0", "Loopback0", None),
            ("swp[1-64]", 64, "swp1", "swp64", ["profile-interface-spine"]),
        ],
    ),
    "cumulus-spectrum3-spine-switch": (
        ["Cumulus", "Cumulus-SPECTRUM3"],
        [
            ("Loopback0", 1, "Loopback0", "Loopback0", None),
            ("swp[1-32]", 32, "swp1", "swp32", ["profile-interface-leaf"]),
            ("swp[33-64]", 32, "swp33", "swp64", ["profile-interface-super-spine"]),
        ],
    ),
    "cumulus-spectrum4-super-spine-switch": (
        ["Cumulus", "Cumulus-SPECTRUM4"],
        [
            ("Loopback0", 1, "Loopback0", "Loopback0", None),
            ("swp[1-64]", 64, "swp1", "swp64", ["profile-interface-spine"]),
        ],
    ),
    "cumulus-spectrum4-spine-switch": (
        ["Cumulus", "Cumulus-SPECTRUM4"],
        [
            ("Loopback0", 1, "Loopback0", "Loopback0", None),
            ("swp[1-32]", 32, "swp1", "swp32", ["profile-interface-leaf"]),
            ("swp[33-64]", 32, "swp33", "swp64", ["profile-interface-super-spine"]),
        ],
    ),
    "cumulus-spectrum2-tor-leaf-switch-compute": (
        ["Cumulus", "Cumulus-SPECTRUM2-TOR"],
        [
            ("Loopback0", 1, "Loopback0", "Loopback0", None),
            ("swp[1-48]", 48, "swp1", "swp48", ["profile-interface-server"]),
            ("swp[49-54]", 6, "swp49", "swp54", ["profile-interface-spine"]),
        ],
    ),
    "cumulus-spectrum2-tor-leaf-switch-storage": (
        ["Cumulus", "Cumulus-SPECTRUM2-TOR"],
        [
            ("Loopback0", 1, "Loopback0", "Loopback0", None),
            ("swp[1-48]", 48, "swp1", "swp48", ["profile-interface-compute"]),
            ("swp[49-54]", 6, "swp49", "swp54", ["profile-interface-spine"]),
        ],
    ),
}

# template_name -> expected top-level device-role. A copy-paste bug swapping spine/super_spine
# between sibling templates would leave every other assertion in this file green.
EXPECTED_ROLES: dict[str, str] = {
    "cumulus-spectrum2-super-spine-switch": "super_spine",
    "cumulus-spectrum2-spine-switch": "spine",
    "cumulus-spectrum3-super-spine-switch": "super_spine",
    "cumulus-spectrum3-spine-switch": "spine",
    "cumulus-spectrum4-super-spine-switch": "super_spine",
    "cumulus-spectrum4-spine-switch": "spine",
    "cumulus-spectrum2-tor-leaf-switch-compute": "leaf",
    "cumulus-spectrum2-tor-leaf-switch-storage": "leaf",
}

SPINE_AND_SUPER_SPINE_INTERFACE_COUNT = 65
LEAF_INTERFACE_COUNT = 55


def _load_device_templates() -> dict[str, dict[str, Any]]:
    """Parse `objects/06_device_template.yml` and index its `data` entries by `template_name`."""
    document = yaml.safe_load(DEVICE_TEMPLATE_FILE.read_text(encoding="utf-8"))
    entries = document["spec"]["data"]
    return {entry["template_name"]: entry for entry in entries}


def _cumulus_template_names(templates: dict[str, dict[str, Any]]) -> list[str]:
    return sorted(name for name in templates if name.startswith("cumulus-"))


class TestCumulusDeviceTemplatesExist:
    def test_exactly_eight_cumulus_templates_are_declared(self) -> None:
        templates = _load_device_templates()
        assert _cumulus_template_names(templates) == sorted(EXPECTED_TEMPLATES)


class TestCumulusDeviceTemplateWiring:
    @pytest.mark.parametrize("template_name", sorted(EXPECTED_TEMPLATES))
    def test_device_type_matches_intended_chipset_role_pairing(self, template_name: str) -> None:
        templates = _load_device_templates()
        expected_device_type, _ = EXPECTED_TEMPLATES[template_name]

        assert templates[template_name]["device_type"] == expected_device_type

    @pytest.mark.parametrize("template_name", sorted(EXPECTED_TEMPLATES))
    def test_declared_interface_ranges_expand_as_expected(self, template_name: str) -> None:
        templates = _load_device_templates()
        _, expected_interfaces = EXPECTED_TEMPLATES[template_name]

        declared = templates[template_name]["interfaces"]["data"]
        declared_names = [interface["name"] for interface in declared]
        expected_names = [pattern for pattern, _count, _first, _last, _profiles in expected_interfaces]
        assert declared_names == expected_names

        declared_profiles = [interface.get("profiles") for interface in declared]
        expected_profiles = [profiles for _pattern, _count, _first, _last, profiles in expected_interfaces]
        assert declared_profiles == expected_profiles, f"{template_name}: profiles mismatch"

        for pattern, expected_count, expected_first, expected_last, _profiles in expected_interfaces:
            expanded = range_expansion(pattern)
            assert len(expanded) == expected_count, f"{template_name}: {pattern} expanded to {len(expanded)}"
            assert expanded[0] == expected_first, f"{template_name}: {pattern} first name {expanded[0]}"
            assert expanded[-1] == expected_last, f"{template_name}: {pattern} last name {expanded[-1]}"

    @pytest.mark.parametrize("template_name", sorted(EXPECTED_TEMPLATES))
    def test_device_role_matches_intended_tier(self, template_name: str) -> None:
        templates = _load_device_templates()
        assert templates[template_name]["role"] == EXPECTED_ROLES[template_name]

    @pytest.mark.parametrize("template_name", sorted(EXPECTED_TEMPLATES))
    def test_expand_range_is_enabled_on_the_interfaces_block(self, template_name: str) -> None:
        """A dropped `expand_range` flag would leave bracket patterns un-expanded at load time --
        this test's own use of `range_expansion()` above is independent of that flag, so it must be
        asserted directly rather than assumed."""
        templates = _load_device_templates()
        assert templates[template_name]["interfaces"]["parameters"]["expand_range"] is True

    @pytest.mark.parametrize(
        "template_name",
        [name for name in EXPECTED_TEMPLATES if name.endswith("-spine-switch") or "super-spine" in name],
    )
    def test_spine_and_super_spine_templates_total_65_interfaces(self, template_name: str) -> None:
        templates = _load_device_templates()
        declared = templates[template_name]["interfaces"]["data"]

        total = sum(len(range_expansion(interface["name"])) for interface in declared)
        assert total == SPINE_AND_SUPER_SPINE_INTERFACE_COUNT

    @pytest.mark.parametrize(
        "template_name",
        ["cumulus-spectrum2-tor-leaf-switch-compute", "cumulus-spectrum2-tor-leaf-switch-storage"],
    )
    def test_leaf_templates_total_55_interfaces(self, template_name: str) -> None:
        templates = _load_device_templates()
        declared = templates[template_name]["interfaces"]["data"]

        total = sum(len(range_expansion(interface["name"])) for interface in declared)
        assert total == LEAF_INTERFACE_COUNT

    @pytest.mark.parametrize("template_name", sorted(EXPECTED_TEMPLATES))
    def test_exactly_one_loopback0_with_loopback_role_and_no_profile(self, template_name: str) -> None:
        templates = _load_device_templates()
        declared = templates[template_name]["interfaces"]["data"]

        loopbacks = [interface for interface in declared if interface["name"] == "Loopback0"]
        assert len(loopbacks) == 1
        assert loopbacks[0]["role"] == "loopback"
        assert "profiles" not in loopbacks[0]
