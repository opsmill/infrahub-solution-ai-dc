# Contract: Cumulus Registration

What must be registered for a Cumulus device to receive exactly one Cumulus startup-config artifact. Two
`.infrahub.yml` entries, one group, one tuple entry. Additive only — no existing entry is modified.

## 1. Vendor allow-list

`src/infrahub_solution_ai_dc/vendors.py`

```diff
-SUPPORTED_VENDORS: tuple[str, ...] = ("cisco", "arista", "dell", "juniper", "sonic")
+SUPPORTED_VENDORS: tuple[str, ...] = ("cisco", "arista", "dell", "juniper", "sonic", "cumulus")
```

**This is the entire Python delta for the feature.** The group name `cumulus_devices` is derived, not
declared, by `vendor_group_for_manufacturer`.

## 2. Vendor group

`objects/01_groups.yml` — appended to the five existing vendor groups:

```yaml
    - name: cumulus_devices
      parent: devices
```

## 3. Jinja2 transform

`.infrahub.yml`, appended after the `sonic_device_startup_config` entry:

```yaml
  - name: cumulus_device_startup_config
    description: "Cumulus Linux device config transform"
    query: "network_device_startup_config"
    template_path: "./transforms/templates/startup_config_cumulus.j2"
```

`query` is the **existing shared query**, registered once in `.infrahub.yml`
(`./transforms/startup_config.gql`). It is not modified and not duplicated.

## 4. Artifact definition

`.infrahub.yml`, appended after the `sonic_startup_configuration` entry:

```yaml
  - name: "cumulus_startup_configuration"
    artifact_name: "Startup configuration"
    parameters:
      name: "hostname__value"
    content_type: "text/plain"
    targets: "cumulus_devices"
    transformation: "cumulus_device_startup_config"
```

`artifact_name` **must** stay `"Startup configuration"`, identical to the other five. Integration tests fetch
artifacts by that name, and it is what makes the artifact read identically regardless of vendor.

## Invariants

1. **Exactly one artifact per device.** No artifact definition may target the `devices` group. Each device is
   a member of `devices` **and** exactly one `{vendor}_devices` group; artifact definitions target only the
   vendor groups, so each device renders exactly one startup config. Adding Cumulus must not change this.
2. **The query is shared, never forked.** All six transforms reference `network_device_startup_config`.
3. **The group name is derived, not configured.** `cumulus_devices` follows from the manufacturer name
   `Cumulus`; it must not be spelled differently in `objects/01_groups.yml` than `f"{name.lower()}_devices"`
   produces, or artifact targeting silently matches nothing.
4. **Membership is stamped by generators, not declared in data.** `objects/01_groups.yml` creates the empty
   group; `generate_fabric.py`, `generate_pod.py` and `generate_rack.py` populate it.

## Resolution chain

```text
OrganizationManufacturer.name = "Cumulus"
  └─ NetworkDeviceType.manufacturer          (objects/03_device_type.yml)
       └─ TemplateNetworkDevice.device_type  (objects/06_device_template.yml)
            └─ vendor_group_for_template()   (vendors.py, called once per generator run)
                 └─ "cumulus_devices"        (vendors.py)
                      └─ member_of_groups=["devices", "cumulus_devices"]
                           └─ artifact_definitions.targets: "cumulus_devices"
                                └─ cumulus_device_startup_config
                                     └─ transforms/templates/startup_config_cumulus.j2
```

Any break in this chain surfaces as a device with **zero** artifacts rather than an error — which is why the
quickstart checks artifact counts explicitly rather than only checking that configs look right.

## Failure mode to preserve

`vendor_group_for_manufacturer` raises a `ValueError` naming the device when a manufacturer is missing or
unsupported. This behaviour must survive the change: adding Cumulus widens the allow-list by exactly one
entry and must not weaken the fail-loud contract for any other manufacturer.

The negative-path example in `tests/unit/test_vendors.py` (`"Nokia"`) remains unsupported after this change —
only `"cumulus"` is being added — so it needs no change. Add `("Cumulus", "cumulus_devices")` to the
happy-path parametrize.
