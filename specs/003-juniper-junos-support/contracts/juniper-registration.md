# Contract: Juniper Registration

What must be registered for a Juniper device to receive exactly one Junos startup-config artifact. Two
`.infrahub.yml` entries, one group, one tuple entry. Additive only — no existing entry is modified.

## 1. Vendor allow-list

`src/infrahub_solution_ai_dc/vendors.py:24`

```diff
-SUPPORTED_VENDORS: tuple[str, ...] = ("cisco", "arista", "dell")
+SUPPORTED_VENDORS: tuple[str, ...] = ("cisco", "arista", "dell", "juniper")
```

**This is the entire Python delta for the feature.** The group name `juniper_devices` is derived, not
declared, by `vendor_group_for_manufacturer` at `vendors.py:45`.

## 2. Vendor group

`objects/01_groups.yml` — appended to the three existing vendor groups:

```yaml
    - name: juniper_devices
      parent: devices
```

## 3. Jinja2 transform

`.infrahub.yml`, appended after the `dell_device_startup_config` entry (currently ends at line 91):

```yaml
  - name: juniper_device_startup_config
    description: "Juniper device config transform"
    query: "network_device_startup_config"
    template_path: "./transforms/templates/startup_config_juniper.j2"
```

`query` is the **existing shared query** registered at `.infrahub.yml:24-25`
(`./transforms/startup_config.gql`). It is not modified and not duplicated.

## 4. Artifact definition

`.infrahub.yml`, appended after the `dell_startup_configuration` entry (currently ends at line 129):

```yaml
  - name: "juniper_startup_configuration"
    artifact_name: "Startup configuration"
    parameters:
      name: "hostname__value"
    content_type: "text/plain"
    targets: "juniper_devices"
    transformation: "juniper_device_startup_config"
```

`artifact_name` **must** stay `"Startup configuration"`, identical to the other three. Integration tests
fetch artifacts by that name (`tests/integration/test_overlay_daytwo.py:5,71,97`), and it is what makes the
artifact read identically regardless of vendor.

## Invariants

1. **Exactly one artifact per device.** No artifact definition may target the `devices` group. Each device is
   a member of `devices` **and** exactly one `{vendor}_devices` group; artifact definitions target only the
   vendor groups, so each device renders exactly one startup config. Adding Juniper must not change this.
2. **The query is shared, never forked.** All four transforms reference `network_device_startup_config`.
3. **The group name is derived, not configured.** `juniper_devices` follows from the manufacturer name
   `Juniper`; it must not be spelled differently in `objects/01_groups.yml` than
   `f"{name.lower()}_devices"` produces, or artifact targeting silently matches nothing.
4. **Membership is stamped by generators, not declared in data.** `objects/01_groups.yml` creates the empty
   group; `generate_fabric.py:65`, `generate_pod.py:118` and `generate_rack.py:164` populate it.

## Resolution chain

```text
OrganizationManufacturer.name = "Juniper"
  └─ NetworkDeviceType.manufacturer          (objects/03_device_type.yml)
       └─ TemplateNetworkDevice.device_type  (objects/06_device_template.yml)
            └─ vendor_group_for_template()   (vendors.py:48-69, called once per generator run)
                 └─ "juniper_devices"        (vendors.py:45)
                      └─ member_of_groups=["devices", "juniper_devices"]
                           └─ artifact_definitions.targets: "juniper_devices"
                                └─ juniper_device_startup_config
                                     └─ transforms/templates/startup_config_juniper.j2
```

Any break in this chain surfaces as a device with **zero** artifacts rather than an error — which is why the
quickstart checks artifact counts explicitly rather than only checking that configs look right.

## Failure mode to preserve

`vendor_group_for_manufacturer` raises a `ValueError` naming the device when a manufacturer is missing or
unsupported (`vendors.py:33-43`). This behaviour must survive the change: adding Juniper widens the
allow-list by exactly one entry and must not weaken the fail-loud contract for any other manufacturer.

`tests/unit/test_vendors.py:32-35` currently asserts this using **`"Juniper"`** as the unsupported example
and **will fail** once Juniper is supported. It must be re-pointed at a still-unsupported manufacturer
(e.g. `"Nokia"`), and `("Juniper", "juniper_devices")` added to the happy-path parametrize at `:14-17`.
