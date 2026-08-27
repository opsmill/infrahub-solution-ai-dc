# Contract: SONiC Registration

What must be registered for a SONiC device to receive exactly one SONiC startup-config artifact. Two
`.infrahub.yml` entries, one group, one tuple entry. Additive only — no existing entry is modified.

## 1. Vendor allow-list

`src/infrahub_solution_ai_dc/vendors.py`

```diff
-SUPPORTED_VENDORS: tuple[str, ...] = ("cisco", "arista", "dell", "juniper")
+SUPPORTED_VENDORS: tuple[str, ...] = ("cisco", "arista", "dell", "juniper", "sonic")
```

**This is the entire Python delta for the feature.** The group name `sonic_devices` is derived, not declared,
by `vendor_group_for_manufacturer`.

## 2. Vendor group

`objects/01_groups.yml` — appended to the four existing vendor groups:

```yaml
    - name: sonic_devices
      parent: devices
```

## 3. Jinja2 transform

`.infrahub.yml`, appended after the `juniper_device_startup_config` entry:

```yaml
  - name: sonic_device_startup_config
    description: "SONiC device config transform"
    query: "network_device_startup_config"
    template_path: "./transforms/templates/startup_config_sonic.j2"
```

`query` is the **existing shared query**, registered once in `.infrahub.yml`
(`./transforms/startup_config.gql`). It is not modified and not duplicated.

## 4. Artifact definition

`.infrahub.yml`, appended after the `juniper_startup_configuration` entry:

```yaml
  - name: "sonic_startup_configuration"
    artifact_name: "Startup configuration"
    parameters:
      name: "hostname__value"
    content_type: "text/plain"
    targets: "sonic_devices"
    transformation: "sonic_device_startup_config"
```

`artifact_name` **must** stay `"Startup configuration"`, identical to the other four. Integration tests fetch
artifacts by that name, and it is what makes the artifact read identically regardless of vendor.

## Invariants

1. **Exactly one artifact per device.** No artifact definition may target the `devices` group. Each device is
   a member of `devices` **and** exactly one `{vendor}_devices` group; artifact definitions target only the
   vendor groups, so each device renders exactly one startup config. Adding SONiC must not change this.
2. **The query is shared, never forked.** All five transforms reference `network_device_startup_config`.
3. **The group name is derived, not configured.** `sonic_devices` follows from the manufacturer name `SONiC`;
   it must not be spelled differently in `objects/01_groups.yml` than `f"{name.lower()}_devices"` produces,
   or artifact targeting silently matches nothing.
4. **Membership is stamped by generators, not declared in data.** `objects/01_groups.yml` creates the empty
   group; `generate_fabric.py`, `generate_pod.py` and `generate_rack.py` populate it.

## Resolution chain

```text
OrganizationManufacturer.name = "SONiC"
  └─ NetworkDeviceType.manufacturer          (objects/03_device_type.yml)
       └─ TemplateNetworkDevice.device_type  (objects/06_device_template.yml)
            └─ vendor_group_for_template()   (vendors.py, called once per generator run)
                 └─ "sonic_devices"          (vendors.py)
                      └─ member_of_groups=["devices", "sonic_devices"]
                           └─ artifact_definitions.targets: "sonic_devices"
                                └─ sonic_device_startup_config
                                     └─ transforms/templates/startup_config_sonic.j2
```

Any break in this chain surfaces as a device with **zero** artifacts rather than an error — which is why the
quickstart checks artifact counts explicitly rather than only checking that configs look right.

## Failure mode to preserve

`vendor_group_for_manufacturer` raises a `ValueError` naming the device when a manufacturer is missing or
unsupported. This behaviour must survive the change: adding SONiC widens the allow-list by exactly one entry
and must not weaken the fail-loud contract for any other manufacturer.

`tests/unit/test_vendors.py` was re-pointed once already (from `"Juniper"` to a still-unsupported example,
`003`'s D9) when Juniper was added. Confirm the current negative-path example is still an unsupported
manufacturer after this change — it will still not be, since only `"sonic"` is being added — and add
`("SONiC", "sonic_devices")` to the happy-path parametrize.
