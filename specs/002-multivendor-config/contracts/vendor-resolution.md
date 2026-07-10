# Contract: Vendor Resolution & Group Membership (generators)

How the three topology generators put each device into its vendor group, without forking per vendor.

## Shared helper — `src/infrahub_solution_ai_dc/vendors.py`

```python
# Signature contract (illustrative)
async def vendor_group_for_device(client, device_id: str) -> str:
    """Resolve a device's vendor group name from its manufacturer.

    Fetches NetworkDevice.device_type.manufacturer.name and returns
    f"{name.lower()}_devices". Raises a clear ValueError naming the device if
    the manufacturer cannot be resolved (spec FR-004 / SC-004).
    """
```

- Input: an Infrahub client + a device id (or a device node already including `device_type`).
- Output: one of `cisco_devices`, `arista_devices`, `dell_devices`.
- Error: `ValueError` (or a project error type) whose message includes the device hostname/id when
  `device_type`, `manufacturer`, or `manufacturer.name` is missing/unknown. **No fallback, no skip.**

## Generator integration (all three: fabric / pod / rack)

The generators already re-fetch each freshly created device to assign its loopback (e.g.
`generate_fabric.py:65`, `generate_rack.py:165`). Extend that step:

```python
# after create + save with member_of_groups=["devices"]
device = await self.client.get(
    NetworkDevice, id=device.id,
    include=["ip_address", "device_type", "member_of_groups"],
)
group = await vendor_group_for_device(self.client, device.id)  # raises if unresolved
device.member_of_groups.add(group)      # add vendor child group in addition to "devices"
await device.save(allow_upsert=True)
```

- Applies to `create_super_spine_switches` (fabric), spine creation (pod), and `create_leaf_switches` (rack).
- **No `.gql` change** — the vendor is read via the SDK `client.get` include, not the generator query.
- The generator stays a single class per topology level (spec FR-002).

## Idempotency

- Re-runs resolve the same group and re-add the same membership under `allow_upsert=True` → no duplicates,
  no checksum churn (membership add mirrors the existing `member_of_groups=["devices"]` behavior).

## Invariants

- Every generated device ends up in `devices` + exactly one `{vendor}_devices` group (spec SC-001).
- An unresolvable manufacturer aborts generation with a device-naming error (spec SC-004) — which is why the
  dataset cleanup (remove vendor-less templates, re-vendor Fabric-A) must land together with this change.
