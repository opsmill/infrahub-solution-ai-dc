# Phase 0 Research: Juniper / Junos Vendor Support

All spec decisions were resolved with the user during the grilling session. This file records each decision
with rationale, alternatives, and the **verified** mechanics that make it implementable. Where a claim was
checked against the code or a live interpreter, the evidence is stated. No `NEEDS CLARIFICATION` markers
remain.

## D1 — Vendor registration: one tuple entry

- **Decision**: Add `"juniper"` to `SUPPORTED_VENDORS` in `src/infrahub_solution_ai_dc/vendors.py`. Nothing
  else in that module changes.
- **Rationale**: `vendor_group_for_manufacturer` derives the group name as
  `f"{name.strip().lower()}_devices"`, so `juniper_devices` follows automatically once the vendor is allowed.
- **Verified mechanic**: `vendors.py:24` is the single allow-list; `vendors.py:45` does the derivation;
  `vendor_group_for_template` walks `TemplateNetworkDevice.device_type → NetworkDeviceType.manufacturer →
  OrganizationManufacturer.name` and delegates to the same function. The three generators call it once each
  (`generate_fabric.py:41`, `generate_pod.py:93`, `generate_rack.py:65`) and stamp
  `member_of_groups=["devices", self.vendor_group]`.
- **Consequence**: **No generator file changes.** This is the direct evidence for spec SC-002.

## D2 — Interface naming: authentic Junos, and it is safe

- **Decision**: Use real Junos names — `et-0/0/N` for 400G/100G ports, `xe-0/0/N` for the 10/25G access
  ports. Do not fall back to vendor-neutral `Ethernet` naming.
- **Rationale**: The primary user is a Juniper engineer who would immediately notice `Ethernet1/1` on a QFX.
- **Risk investigated**: Juniper is the **only** vendor whose leaf carries two interface-name families, so
  alphabetical ordering (`et-` before `xe-`) is the reverse of port order. Every existing vendor's leaf uses
  a single `Ethernet…` family where sorted order equals port order.
- **Verified safe**: `netutils.interface.sort_interface_list` orders Junos names numerically within a family
  (`et-0/0/0` → `et-0/0/1` → `et-0/0/2` → `et-0/0/10`), confirmed in a live interpreter. More importantly,
  **all four sort call sites are fed by role-filtered queries** — `generate_pod.py:256,261` then `:258,263`,
  and `generate_rack.py:184,189` then `:187,194`, each preceded by
  `client.filters(..., role__value=...)`. Uplinks (role `spine`) and access ports (role `server`/`storage`)
  are therefore never sorted together. The cross-family ordering quirk cannot reach the cabling algorithm.
- **Residual risk (recorded, not mitigated)**: any *future* code that sorts an unfiltered interface list
  would hit this. Worth a comment at the naming site.
- **Alternatives considered**: vendor-neutral `Ethernet` names rendered as Junos in-template — rejected,
  it makes the data model lie about the hardware for the one user who would notice.

## D3 — Range expansion handles the Junos name form

- **Question**: The existing templates use `Ethernet1/[1-32]`. Does the object loader's range expansion
  handle `et-0/0/[48-55]` and `xe-0/0/[0-47]`?
- **Verified**: Yes. `infrahub_sdk.spec.range_expansion.range_expansion` was run directly against all four
  forms:

  | Pattern | Items | First | Last |
  |---|---|---|---|
  | `Ethernet1/[1-32]` | 32 | `Ethernet1/1` | `Ethernet1/32` |
  | `et-0/0/[0-63]` | 64 | `et-0/0/0` | `et-0/0/63` |
  | `et-0/0/[48-55]` | 8 | `et-0/0/48` | `et-0/0/55` |
  | `xe-0/0/[0-47]` | 48 | `xe-0/0/0` | `xe-0/0/47` |

- **Consequence**: This closes the last open question carried out of the grilling session. `expand_range:
  true` works unchanged for Juniper.

## D4 — Loopbacks: vendor-neutral names, mapped in-template

- **Decision**: Object templates declare `Loopback0` (role `loopback`); the VTEP loopback stays `Loopback1`
  (role `vtep`), created at runtime. The Junos template maps them to `lo0` unit 0 and unit 1.
- **Rationale**: Junos genuinely models one `lo0` with multiple units, so a 1:1 mapping is a faithful
  rendering rather than a workaround. It also keeps `src/infrahub_solution_ai_dc/addressing.py:64`
  (`interface_name: str = "Loopback1"`) and the generators free of vendor logic, protecting SC-002.
- **Alternative rejected**: naming them `lo0.0`/`lo0.1` in the data. It would force `addressing.py` to take a
  vendor-aware name and `generate_rack.py` to resolve the vendor before allocating the VTEP loopback —
  pushing vendor branching into the generators, which is exactly what `002` was designed to avoid.
- **Domain consequence, recorded**: `CONTEXT.md` previously described `loopback0`/`loopback1` as interface
  names. They are now **logical names carried in the data model, rendered per-vendor**, with interface
  **role** as the reliable discriminator. Three `CONTEXT.md` edits were applied during the grilling session
  (Vendor group, VTEP, and the flagged-ambiguity entry).

## D5 — Junos config: curly-brace hierarchical, default-switch EVPN model

- **Decision**: Emit curly-brace hierarchical configuration (what `show configuration` returns), using the
  Junos **default-switch** EVPN model — `switch-options` + `vlans` + `routing-instances` — not MAC-VRF.
- **Rationale**: The other three artifacts are full startup configurations, not paste-in command scripts, so
  hierarchical output is the consistent choice. The default-switch model is the simpler of the two Junos
  EVPN expressions and is the right level for a reference solution.
- **Structural consequence**: This is the one place the Juniper template genuinely departs from the other
  three. Cisco/Arista/Dell emit one flat `interface <name>` stanza per interface in a single unfiltered loop
  (`startup_config_arista.j2:39-41`). Junos nests everything under `interfaces { }`, and **both loopbacks are
  units of one `lo0`** — so the template must collect the `loopback`- and `vtep`-role interfaces and emit a
  single `lo0` stanza, rather than looping them independently. See
  [contracts/junos-config-contract.md](./contracts/junos-config-contract.md).
- **Alternative rejected**: `set`-command style. Easier to diff line-by-line, but inconsistent with the
  "startup configuration" framing of the other three artifacts.

## D6 — No automated template validation

- **Decision**: Ship with **no** configuration-template test, golden file, or Junos parser. Correctness is
  established by human review (spec SC-001).
- **Rationale**: Consistent with the existing three vendors, none of which has a template test. The repo's
  only artifact-level test (`tests/integration/test_overlay_daytwo.py`) does byte-comparison before/after a
  change and never inspects content.
- **Accepted with open eyes**: hierarchical config has a failure mode the flat dialects do not — a
  mis-scoped Jinja loop yields unbalanced braces and structurally invalid output, where a flat template would
  yield one wrong line. A brace-balance + role-based structural test was proposed and **declined** in favour
  of manual review.
- **Mitigation**: SC-001 puts a reviewer with production Junos experience on the critical path, with a
  **scoped mandate** — Junos syntax, stanza placement and EVPN/VXLAN structure only. Management addressing,
  MTU and operational services are known repo-wide simplifications shared by all four vendors and are
  explicitly outside the review, or the review would fail on deliberate choices.

## D7 — Hardware: QFX5230-64CD and QFX5120-48Y-8C, with all 8 uplinks

- **Decision**: Spine and super-spine on **QFX5230-64CD** (64× 400G, `et-0/0/[0-63]`); leaf on
  **QFX5120-48Y-8C** (48× 10/25G `xe-0/0/[0-47]` + 8× 100G `et-0/0/[48-55]`).
- **Rationale**: Closest Juniper equivalents to the 64-port and 48+uplink models the other three vendors use,
  keeping the four fabrics comparable side by side.
- **The 8-vs-4 uplink question**: the other vendors' leaves declare 4 uplinks; the QFX5120-48Y-8C genuinely
  has 8. Cabling takes `src_interfaces[:dst_device_count]` = 4 (one per spine), leaving 4 uncabled per leaf.
  The initial instinct was to declare only 4 to avoid dangling stanzas — **reversed on evidence**: the
  interface loop in every existing template iterates `device.interfaces.edges` unfiltered and emits a stanza
  for every interface, so each Cisco/Arista/Dell leaf config **already renders 48 shutdown, address-less
  access-port stanzas**. Four more changes nothing, while declaring 4 ports would be factually wrong about
  the hardware in front of the one user who would notice.
- **Alternatives considered**: QFX5240-64OD + QFX5130-32CD (newer, but the leaf is a high-radix 400G box that
  diverges from the other vendors' access-leaf shape); QFX10008 chassis spine (slot/PIC interface naming
  diverges from the fixed-form pattern).

## D8 — Demo data: full Fabric-D, inside the P1 slice

- **Decision**: Ship Fabric-D (Juniper) mirroring Fabric-B/C exactly — 4 super-spines, Pod-D1 (`role:
  fabric`) / Pod-D2 / Pod-D3, and 8 racks in `Hall-A1`.
- **Rationale**: "Plumbing only" delivers nothing observable to the evaluator and cannot be inspected — with
  no template tests, the demo fabric **is** the verification harness. A trimmed Fabric-D would deliver the
  same inspection value more cheaply but would be the only asymmetric fabric in the UI.
- **Cost, measured**: Fabric-A 25 devices, Fabric-B 23, Fabric-C 23; Fabric-D adds 23, taking the demo from
  ~71 to ~94 (+32%), plus ~1,400 interfaces. `amount_of_spines` defaults to 4 (`schemas/logical_design.yml:109`)
  and `amount_of_super_spines` to 4 (`:36`), which is why Fabric-B/C do not set the spine count explicitly.
- **Verified mechanic**: `generate_fabric.py:113` (`allocate_resource_pools`) carves a per-fabric `/16` from
  `FabricSupernetPool` (10.0.0.0/8) keyed by fabric id and allocates the overlay ASN from a pool — so
  **Fabric-D needs no manual addressing or ASN**, exactly as Fabric-C did not.

## D9 — The existing negative test will fail and must be re-pointed

- **Finding**: `tests/unit/test_vendors.py:32-35` (`test_unsupported_manufacturer_raises_naming_device`) uses
  **`"Juniper"`** as its unsupported-vendor example and asserts `"Juniper" in str(exc.value)`. Adding Juniper
  to `SUPPORTED_VENDORS` makes this test fail.
- **Action**: Re-point it at a genuinely unsupported manufacturer (e.g. `"Nokia"`), and add
  `("Juniper", "juniper_devices")` to the happy-path parametrize at `:14-17`.
- **Note**: `test_every_supported_vendor_resolves` (`:23-25`) iterates `SUPPORTED_VENDORS` and picks up the
  new vendor with no edit.

## Cross-cutting: what does not change

Confirmed by inspection, and asserted as spec SC-002:

- **No schema change.** There is no vendor enum anywhere in `schemas/`; `OrganizationManufacturer.name` is a
  free-text unique `Text` attribute. `protocols.py` is therefore **not** regenerated.
- **No generator change.** Vendor resolution already runs in all three generators via `vendors.py`.
- **No GraphQL change.** `transforms/startup_config.gql` already returns every field a Junos template needs.
  (`NetworkInterface.mtu` exists in the schema but is not queried and is not rendered by any vendor — out of
  scope, see spec.)
- **No new dependency, no CI change, no auth change.**

## Out-of-scope issue observed, deliberately not fixed

The computed `index` attribute (`schemas/device.yml:216`,
`{{ "%03d"| format(name__value | split_interface | last | int) }}`) renders **`000` for every Cisco and Dell
interface today** — Jinja's `int` filter swallows `int("1/5")` and returns 0. Only Arista's flat names
produce a real index. Junos names behave identically (`et-0/0/0` → `("et-", "0/0/0")` → `000`), verified in a
live interpreter. This is **pre-existing, vendor-wide, and out of scope** — Juniper neither introduces nor
worsens it. Recorded because `NetworkInterface.order_by: ["index__value"]` depends on the attribute, and
because anyone reading the Junos template will notice it.
