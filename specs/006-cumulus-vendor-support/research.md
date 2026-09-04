# Phase 0 Research: NVIDIA Cumulus Linux Vendor Support

This file records each design decision with rationale and the mechanics that make it implementable, following
the same standard `specs/005-sonic-vendor-support/research.md` set (the fifth vendor added under the
`002-multivendor-config` pattern; this is the sixth). Where a claim was checked against the code in this
repository, that check is stated. Where a claim is about Cumulus Linux/FRR itself rather than this codebase, it
is stated as a documented convention to be confirmed by the human reviewer at SC-001, not as something
verified here. No `NEEDS CLARIFICATION` markers remain.

## D1 — Vendor registration: one tuple entry

- **Decision**: Add `"cumulus"` to `SUPPORTED_VENDORS` in `src/infrahub_solution_ai_dc/vendors.py`. Nothing
  else in that module changes.
- **Rationale**: `vendor_group_for_manufacturer` derives the group name as
  `f"{name.strip().lower()}_devices"`, so `cumulus_devices` follows automatically once the vendor is allowed.
- **Verified mechanic**: `vendors.py:24` is the single allow-list; `vendors.py:45` does the derivation;
  `vendor_group_for_template` walks `TemplateNetworkDevice.device_type → NetworkDeviceType.manufacturer →
  OrganizationManufacturer.name` and delegates to the same function. The three generators
  (`generate_fabric.py`, `generate_pod.py`, `generate_rack.py`) call it once each and stamp
  `member_of_groups=["devices", self.vendor_group]`.
- **Consequence**: **No generator file changes.** This is the direct evidence for spec SC-002, exactly as it
  was for SONiC.

## D2 — "Manufacturer" models the config dialect, not a legal hardware maker

- **Decision**: Add one `OrganizationManufacturer` named `Cumulus`. Device types under it are named after
  the NVIDIA Spectrum ASIC generation, following the precedent D7 (below) and SONiC's own D2/D7 already set.
- **Rationale**: `OrganizationManufacturer.name` is a free-text unique `Text` attribute with no vendor enum
  anywhere in the schema (unchanged from SONiC's D2 finding — `schemas/device.yml` and `schemas/organization.yml`
  still carry no closed list). Cumulus Linux is an operating system; today it ships primarily as part of
  NVIDIA's own Spectrum-based switch portfolio (NVIDIA acquired Cumulus Networks in 2020), which is a
  narrower case than SONiC's genuinely multi-ODM situation, but the modelling problem is identical: the
  manufacturer field is the identity of the config dialect, not a strict legal-manufacturer record. One
  manufacturer entry named "Cumulus" keeps that pattern intact.
- **Naming, following D7's chipset-generation precedent directly**: device types are named after the
  Spectrum ASIC generation (`Cumulus-SPECTRUM2`/`3`/`4`, `Cumulus-SPECTRUM2-TOR`), not a specific reseller
  SKU — for the same reason SONiC's D7 gave: the ASIC generation, not the box, is what determines forwarding
  capacity and port speed, and it sidesteps any `[manufacturer, name__value]` uniqueness-constraint collision
  with an existing vendor's model number (`schemas/device.yml:38-39`).

## D3 — Interface naming: Cumulus Linux's real front-panel `swp` convention

- **Decision**: Use Cumulus Linux's real, single interface-naming convention — `swpN`, where `N` is the
  sequential front-panel port number, 1-indexed (port 1 → `swp1`, port 2 → `swp2`, …).
- **Rationale**: This is the interface name every Cumulus Linux switch actually uses; there is no alternate
  naming mode to choose between the way SONiC has `alias` vs. `default` (research.md D3 in `005`) — `swpN` is
  simply Cumulus Linux's interface name.
- **Structural simplification relative to SONiC**: `swpN` carries **no slash**, unlike SONiC's `Eth1/N` or
  Dell's `Ethernet1/N`. It is shaped like Arista's flat `EthernetN` naming, not like the slash-delimited
  vendors. This has two downstream consequences, both favourable:
  1. **Range expansion**: `swp[1-64]` is a plain two-number bracket expression — the same
     `infrahub_sdk.spec.range_expansion.range_expansion` mechanic already verified for every existing vendor
     (SONiC research.md D10) handles it with no new code path, confirmed by inspecting `_char_range_expand`'s
     numeric branch, which is naming-convention-agnostic.
  2. **The computed `index` attribute** (`schemas/device.yml:207`,
     `{{ "%03d"| format(name__value | split_interface | last | int) }}`) is expected to render the real port
     number (e.g. `033` for `swp33`), **not** `000` — because `split_interface` only produces an
     unparseable remainder when the name contains a slash (the Cisco/Dell/Junos/SONiC case, documented in
     SONiC research.md's carried-forward note). `swpN` has no slash, so this behaves like Arista's exception,
     not like SONiC's own case. Confirm at implementation time rather than assume, consistent with every
     prior vendor's treatment of this attribute.
- **Sort order**: cabling and rendering both go through
  `create_sorted_device_interface_map`/`create_reverse_sorted_device_interface_map`
  (`src/infrahub_solution_ai_dc/sorting.py`), which delegate to `netutils.interface.sort_interface_list` — a
  numeric-aware sorter. `swp1` … `swp64` is shaped exactly like Arista's `Ethernet1` … `Ethernet64` (prefix +
  bare integer, no separator), an already-proven case for that sorter — not a new one.
- **Alternatives considered**: vendor-neutral sequential numbering with no Cumulus-specific prefix — rejected
  for the same reason every prior vendor rejected it: it is the detail a Cumulus-standardised engineer would
  notice is wrong. A slash-suffixed form (`swp1/1` breakout-style) — rejected because it implies breakout,
  which this feature does not model (see Out of Scope), and no chosen device type is breakout-enabled.

## D4 — Loopbacks: vendor-neutral names, mapped in-template (unchanged pattern from SONiC's D4)

- **Decision**: Object templates declare `Loopback0` (role `loopback`); the VTEP loopback stays `Loopback1`
  (role `vtep`), created at runtime by `generate_rack.py`/`addressing.py` exactly as for every other vendor.
  The Cumulus template maps **both** onto Cumulus Linux's single real loopback interface, `lo` — as two
  separate `address` lines under one `auto lo` / `iface lo` stanza, one per role.
- **Rationale**: Reuses the design `003` established and `005` confirmed: `addressing.py`'s hardcoded
  `Loopback1` and the generators stay vendor-blind; interface **role** remains the reliable discriminator, not
  the literal name. This is also the real, documented Cumulus Linux convention — a Cumulus `lo` stanza
  routinely carries more than one `address` line (the routing-protocol loopback and, in EVPN deployments, a
  second address used as the VXLAN local tunnel IP) — so no synthetic mapping is being invented here; it
  matches how Cumulus operators actually configure this.
- **Consequence**: No change to `addressing.py`, `generate_rack.py`, or `CONTEXT.md`'s existing "vendor
  group / VTEP / role is the discriminator" language.

## D5 — Cumulus config: ifupdown2 stanzas + FRR flat CLI, a third distinct structural shape

- **Decision**: Render Cumulus Linux's configuration as one flat text artifact combining two distinguishable
  syntaxes, in two clearly separated sections:
  1. **`/etc/network/interfaces` (ifupdown2)** — Debian-style declarative **stanzas**: an `auto <name>` line
     (only when the interface is administratively up) followed by an `iface <name>` header and indented
     attribute lines, for physical interfaces, `lo`, the VLAN-aware `bridge`, per-segment `vni<N>` interfaces,
     and per-segment routed `vlan<N>` SVIs.
  2. **FRR routing configuration** (`vtysh`-style, e.g. `router bgp <asn>`, `address-family l2vpn evpn`,
     `neighbor <ip> remote-as <asn>`) for the underlay and EVPN control plane — the same routing daemon SONiC
     uses, so this section is structurally close to `startup_config_sonic.j2`'s own FRR section (research.md
     D5 in `005`), not a new syntax to design from scratch.
- **Rationale — a third distinct structural risk, correctly distinguished from the other two departures this
  repository already carries**:
  - **Junos** (`003`): true hierarchical brace-nesting — a line can be attached at the wrong *nesting depth*.
  - **SONiC** (`005`): two *flat*, unrelated CLI dialects side by side — a line can use the wrong dialect's
    *verb* in the wrong section, but there is no block/indentation structure to get wrong within either
    dialect.
  - **Cumulus (this feature)**: the ifupdown2 half is **stanza-structured but not deeply nested** — exactly
    two levels (a header line, then flat indented attribute lines belonging to it). The actual risk is an
    attribute line rendering **outside its owning stanza** (e.g. a `bridge-access` line appearing after the
    `bridge` stanza's blank-line terminator instead of inside its own `vni<N>` stanza) — shallower than
    Junos's arbitrary-depth nesting, but a real structural risk the three fully-flat vendors and SONiC's own
    dual-flat design do not have. The FRR half carries no new risk of its own — it is the same syntax and the
    same risk class SONiC's FRR section already has.
- **Alternative considered**: render only the two files as delivered on a real device (`/etc/network/interfaces`
  and `/etc/frr/frr.conf`) as two separately-named sections in one artifact rather than one continuous stream.
  Adopted in spirit — see the config contract's banner-comment convention — but not as two literal file
  headers, to match the single "startup configuration" framing this solution already uses for the other five
  vendors (SONiC being the nearest precedent for a two-syntax split in one artifact).
- **Admin-down mechanic, corrected by D12**: the original decision here was `link-down yes` **with the `auto
  <name>` line omitted**, flagged at the time (critique-20260902-154300, E1) as a documented-but-unverified
  Cumulus Linux/ifupdown2 convention. PR review (D12, defect 5) found this backwards: without `auto`,
  `ifreload -a` never processes the stanza, so `link-down yes` has no effect. The real convention is `auto
  <name>` **plus** `link-down yes`, and that is what the template and contract now both specify.

## D6 — No automated template validation

- **Decision**: Ship with **no** configuration-template test, golden file, or ifupdown2/FRR config parser.
  Correctness is established by human review (spec SC-001), exactly as for the five existing vendors.
- **Rationale**: Consistent with `005`'s D6. None of the five existing templates has a template test; the
  repo's only artifact-level test does byte-comparison before/after a change and never inspects content.
- **Mitigation**: SC-001 puts a reviewer with production Cumulus Linux/FRR experience on the critical path,
  with a scoped mandate — the `/etc/network/interfaces`/FRR split and EVPN/VXLAN structure only. Management
  addressing, MTU and operational services are known repo-wide simplifications shared by every vendor and are
  explicitly outside the review, matching `005`'s precedent exactly.

## D7 — Hardware: Spectrum-ASIC-generation device types, not reseller SKUs

- **Decision**: Model spine/super-spine hardware as **three chipset-generation device types** —
  `Cumulus-SPECTRUM2`, `Cumulus-SPECTRUM3`, `Cumulus-SPECTRUM4` — rather than one specific SKU. Leaf hardware
  is `Cumulus-SPECTRUM2-TOR`, an access-optimised port configuration on the same Spectrum-2 generation as the
  established spine device type but a distinct device type (distinguished by port mix, not silicon
  generation — see the note below on why this differs slightly from SONiC's Trident-vs-Tomahawk framing).
- **Difference from SONiC's D7, stated plainly**: Broadcom ships genuinely separate ASIC *families* for
  access (Trident) and spine (Tomahawk) roles, which is why SONiC's leaf device type is a different chip
  family from its three spine/super-spine device types. NVIDIA's Spectrum family does not have that split —
  the same Spectrum silicon serves both roles at different port counts/speeds depending on the SKU. This
  feature therefore reuses the Spectrum-2 generation for the leaf tier (an access-optimised port
  configuration, `Cumulus-SPECTRUM2-TOR`) rather than inventing a separate chip family that does not exist in
  NVIDIA's real lineup. This is a finding, not a shortcut: modelling accuracy is served by *not* mirroring
  SONiC's exact framing here, since the underlying hardware reality differs.
- **Capacity table** (64-port radix held constant across generations by modelling choice, as SONiC's D7 also
  did, so the existing spine/super-spine template shape needs no change per generation, only `device_type`
  does):

  | Device type | ASIC | Switching capacity | Ports (modeled) |
  |---|---|---|---|
  | `Cumulus-SPECTRUM2` | Spectrum-2 | 6.4 Tbps | 64× 100G |
  | `Cumulus-SPECTRUM3` | Spectrum-3 | 12.8 Tbps | 64× 200G |
  | `Cumulus-SPECTRUM4` | Spectrum-4 | 51.2 Tbps | 64× 800G |

  These capacity figures are NVIDIA's own publicly stated per-generation totals; the specific 64-port/per-port
  speed split is this feature's own modelling choice (identical in kind to SONiC's D7 approach), not a claim
  about any single real SKU's exact port configuration. **Maturity note, stated plainly as SONiC's did for its
  own newest generation**: Spectrum-4 is the newest generation modeled here; it is the forward-leaning entry,
  not an equally long-shipping, field-proven generation the way Spectrum-2 is.
- **Leaf**: `Cumulus-SPECTRUM2-TOR` (48× 25G SFP28 access + 6× 100G QSFP28 uplink) — deliberately the same
  48+6 port shape SONiC's `SONiC-TD4` uses, so the fabric topology (uncabled-uplink edge case, per-rack leaf
  counts) is directly comparable across the two most recently added vendors.
- **The 6-vs-4 uplink question**: pods default to `amount_of_spines: 4` (`schemas/logical_design.yml:104`),
  same as every other fabric. `Cumulus-SPECTRUM2-TOR` has 6 uplink ports. Cabling takes
  `src_interfaces[:dst_device_count]` (`cabling.py`), so 2 of the 6 uplinks per leaf go uncabled — rendered
  present-but-disabled, exactly as every other vendor's surplus uplinks already are.

## D8 — Demo data: full Fabric-F, all three Spectrum generations shown together, inside the P1 slice

- **Decision**: Ship Fabric-F (Cumulus) mirroring Fabric-E's structure exactly — 4 super-spines, Pod-F1
  (`role: fabric`) / Pod-F2 / Pod-F3, 8 racks in the existing `Hall-A1` — plus one overlay tenant scoped to
  Fabric-F with a gateway-bearing segment and an L2-only segment, matching FR-011. As SONiC's D8 did for its
  own three chipset generations, each of Fabric-F's three pods is built from a **different** Spectrum
  generation so all three are actually present and interoperating in the rendered demo:

  | Pod | Role | Device type |
  |---|---|---|
  | Pod-F1 | super-spine | `Cumulus-SPECTRUM4` (newest silicon at the aggregation layer) |
  | Pod-F2 | spine | `Cumulus-SPECTRUM2` (most established generation) |
  | Pod-F3 | spine | `Cumulus-SPECTRUM3` (mid-generation) |

  This mirrors SONiC's exact placement rationale (newest at aggregation, established/mid at the two spine
  pods) so the two most recently added vendors tell the same realistic operational story.
- **Why this doesn't complicate the config-rendering side**: the Cumulus template has no chipset-specific
  logic — every field it consumes (interface role, status, IP, BGP session, segment) is identical in shape
  regardless of which of the three device types produced the interface. Mixing generations within one fabric
  is a topology/data decision only; it does not touch `startup_config_cumulus.j2` or the shared query.
- **Rationale**: A vendor capability with no fabric exercising it is invisible to the evaluator and, with no
  template tests (D6), unverifiable — the demo fabric is both the deliverable and the test harness, exactly
  as `005`'s D8 reasoned for SONiC.
- **Verified mechanic**: `generate_fabric.py`'s `allocate_resource_pools` carves a per-fabric `/16` from the
  shared supernet pool and allocates the overlay ASN from a pool keyed by fabric id — Fabric-F needs no manual
  addressing or ASN, exactly as Fabric-E did not.
- **Cost**: proportionate to Fabric-E's addition (~+20% on top of the post-SONiC demo size). Mixing three
  device types across the existing three pods adds **zero** extra devices — it changes which templates
  Pod-F1/F2/F3 already reference, not how many devices each produces.

## D9 — The existing negative test remains unaffected

- **Finding**: `tests/unit/test_vendors.py`'s rejection-path test uses `"Nokia"` as a manufacturer that stays
  unsupported. `"Nokia"` remains not in `SUPPORTED_VENDORS` after this change — only `"cumulus"` is being
  added.
- **Action**: Add a Cumulus happy-path case (`("Cumulus", "cumulus_devices")`) to the parametrized test; no
  change needed to the negative-path fixture. `test_every_supported_vendor_resolves` already extends with no
  edit once `"cumulus"` is added, same as it did for SONiC.

## D10 — Automated guard for device-template wiring (reuses SONiC's D12 precedent)

- **Decision**: Add `tests/unit/test_cumulus_device_templates.py`, structured identically to
  `tests/unit/test_sonic_device_templates.py` (SONiC research.md D12), asserting for all eight Cumulus device
  templates in `objects/06_device_template.yml`:
  1. each template's `device_type` matches the intended ASIC-generation/role pairing;
  2. each template's interfaces expand (via `infrahub_sdk.spec.range_expansion.range_expansion`) to the
     expected count and first/last interface name — 65 for every spine/super-spine template (64 `swpN` +
     `Loopback0`), 55 for both leaf templates (54 `swpN` + `Loopback0`);
  3. each template's top-level `role` matches its intended tier;
  4. `interfaces.parameters.expand_range` is `true` on every template.
- **Rationale**: Eight templates meant to be near-identical copies differing only in
  `template_name`/`device_type` are exactly the shape of change most likely to suffer a silent copy-paste
  error — SONiC's D12 found and closed this gap for its own eight templates; there is no reason for Cumulus's
  eight templates to ship without the same guard, applied from the start this time rather than added
  retroactively.
- **Scope boundary preserved**: this does not contradict D6 (no automated *rendered-config* test). It asserts
  object-data shape, the same surface SONiC's D12 covers.

## Cross-cutting: what does not change

Confirmed by inspection, and asserted as spec SC-002:

- **No schema change.** No vendor enum anywhere in `schemas/`; `OrganizationManufacturer.name` is free-text.
  `protocols.py` is therefore **not** regenerated.
- **No generator change.** Vendor resolution already runs in all three generators via `vendors.py`.
- **No GraphQL change.** `transforms/startup_config.gql` already returns every field every vendor's template
  needs — interfaces (name/description/role/status/ip), BGP sessions, segments, VRF — and the Cumulus template
  needs nothing beyond that set (identical data surface to SONiC's, restated in
  `contracts/cumulus-config-contract.md`).
- **No new dependency, no CI change, no auth change.**

## D11 — One defect caught by post-implementation review

The `speckit-review-errors` pass (run against `HEAD`-at-implementation-start..`HEAD`) found that the
routed-SVI stanza (`iface vlan<vlan_id>`) guarded its emission on `segment.gateway.node` but dereferenced
`segment.vrf.node.name.value` unguarded on the `vrf` line — a segment with a gateway but a null `vrf`
relationship would raise `jinja2.exceptions.UndefinedError` and abort the whole artifact render, not degrade
gracefully. The review noted the identical unguarded chain exists in `startup_config_sonic.j2` too (not a
Cumulus-specific regression, and out of scope to fix there per this feature's FR-010/Out-of-Scope constraint
against touching existing vendor templates) — but there is no reason for Cumulus's own template to ship with
the same gap from day one. Fixed by widening the guard to `{% if segment.gateway.node and segment.vrf.node %}`,
matching the equivalent two-relationship guard already used in the preamble's `vns` namespace loop (research.md
D5's copied-from-SONiC preamble, line 8). Verified: `inv lint` clean after the change; no test exercises this
path directly (D6), consistent with the repo-wide precedent of relying on template-contract review rather than
automated rendered-config tests.

## D12 — Four defects and one scope reversal, caught by PR review (PR #97)

An external review of the merged template (not `speckit-review-errors`, which only ran once at
implementation time per D11 — this was a human/reviewer pass against the live-rendered artifact) found that
the first-draft template, despite parsing cleanly and passing D11's fix, produced output that was neither a
valid `/etc/network/interfaces` nor a valid `frr.conf`, and could not be mechanically split into either.

- **Defect 1 — four alternating dialect sections, not the two D5 promised.** The template interleaved
  ifupdown2 → FRR → ifupdown2 → FRR (underlay interfaces, then underlay/EVPN `router bgp`, then the tenant
  bridge/VNI/VLAN stanzas, then a **second, reopened** `router bgp {{ overlay_asn }}` block for the tenant
  VNI/RD/route-target entries) with a stray `!` — FRR's comment character — introducing an ifupdown2 section
  header, and `#`/`!` comment styles mixed across the boundary. Two separate `router bgp <same-asn>` blocks
  in one `frr.conf` is not valid FRR syntax regardless of the dialect-mixing. Fixed by consolidating into
  the two genuinely contiguous sections D5 always specified: every ifupdown2 stanza first (interfaces, `lo`,
  VRF devices, bridge, per-segment VNI/VLAN, per-VRF L3VNI VXLAN/VLAN — see Defect 2/4 below), then one
  single `router bgp {{ overlay_asn }}` block carrying underlay sessions, EVPN activation, *and* the tenant
  `vni <l2vni>` entries together, followed by the `vrf <name> / vni <l3vni> / exit-vrf` bindings and the new
  per-VRF BGP instances (Defect 4).
- **Defect 2 — the VRF device was referenced but never created.** `iface vlan<vlan_id>`'s `vrf <name>` line
  (and the new L3VNI transit SVI's, Defect 4) has no target without a matching `auto <name> / iface <name> /
  vrf-table auto` stanza — in ifupdown2 that stanza is what actually creates the VRF; without it `ifreload -a`
  would fail. Fixed by rendering one such stanza per materialised VRF, before the bridge stanza. The
  equivalent gap exists in `startup_config_sonic.j2` too (`config interface vrf bind` with no `config vrf
  add`) — inherited, not invented here, and out of scope to fix on SONiC's template per this feature's
  FR-010 constraint, exactly as D11 treated the analogous shared-gap case.
- **Defect 3 (renumbered from the reviewer's own item 5) — `iface lo` was missing `inet loopback`.** Cumulus
  Linux's own default loopback stanza is `iface lo inet loopback`; the template rendered a bare `iface lo`.
  Fixed.
- **Defect 4 — the routed-segment overlay was an incomplete symmetric IRB.** The FRR side had `vrf <name> /
  vni <l3vni> / exit-vrf` (the zebra-level VRF-to-L3VNI binding) but nothing else: no L3VNI VXLAN interface,
  no L3VNI transit SVI, and no per-VRF BGP instance to redistribute the VRF's routes into EVPN — so tenant
  prefixes were never advertised as Type-5 routes. **This reverses this file's own D5/the contract's explicit
  "out of scope: the `router bgp <asn> vrf <name>` per-VRF BGP-instance model" call** — that call
  under-described the tradeoff as a stylistic alternative to the static `vrf/vni/exit-vrf` binding, when the
  two are actually complementary and the static binding alone does not advertise anything. Fixed by adding,
  per materialised VRF: an `auto vni<l3vni>` VXLAN interface and an `auto vlan<l3_vlan_id>` transit SVI in
  the VRF (ifupdown2 — no `address` line, mirroring `startup_config_cisco.j2`'s `interface Vlan<l3_vlan_id>`,
  lines 140-145, which is a transit interface, not a gateway), both added to the shared `bridge`'s
  `bridge-ports`/`bridge-vids`; and a `router bgp {{ overlay_asn }} vrf {{ vrf.name.value }}` instance (FRR)
  with `address-family ipv4 unicast / redistribute connected` and `address-family l2vpn evpn / rd
  <loopback>:<l3vni> / route-target both <vrf.route_target> / advertise ipv4 unicast`. `vrf.l3_vlan_id` and
  `vrf.route_target` — both already queried, both previously listed as "deliberately unused" in the contract
  — are now load-bearing.
- **Defect 5 (renumbered from the reviewer's own item 6) — inactive-port stanzas were inert.** D5's own
  confidence note flagged the omit-`auto`-line convention as "documented, not independently verified" — the
  review's correction: real ifupdown2 practice is `auto <name>` **plus** `link-down yes`, not `auto`'s
  absence. Without `auto`, `ifreload -a` never processes the stanza at all, so `link-down yes` had no effect
  on any of the 50 (of 55) unattached ports on every Fabric-F leaf. Fixed by restoring `auto <name>` on the
  inactive branch, matching the active branch. `contracts/cumulus-config-contract.md` and this file's D5 are
  both updated to drop the now-incorrect omit-`auto` convention rather than merely noting the fix here.
- **Verification method**: same as D13 in `005`'s research.md — a synthetic Jinja2 render (not `inv lint`,
  not a live Infrahub stack) against hand-built mock data matching the shared query's exact field shape,
  covering a Fabric-F leaf with all three tenant segments (two routed, one L2-only) and an uncabled port, plus
  a spine with no segments. Confirmed: exactly two contiguous sections; the VRF stanza precedes every `vrf
  <name>` reference; `iface lo inet loopback`; the inactive port carries both `auto` and `link-down yes`; the
  L3VNI VXLAN/SVI pair and the per-VRF `router bgp ... vrf ...` instance render only on the leaf, never the
  spine (A3 preserved).
- **Not addressed by this review pass**: the reviewer's other findings were explicitly non-defects (house-wide
  `sort()`-determinism reliance on query-order stability; no committed Jinja render tests, D6's known
  tradeoff; `bridge-ports` omitting per-server `swpN` membership, already Out of Scope; the Fabric-E-mirroring
  rack template mismatches, already commented as deliberate) or documentation-only (demo-guide.mdx's stale
  tenant list; quickstart.md's stale artifact-per-device count) — fixed directly in those files, not recorded
  as template decisions here.

## Note carried forward, resolved differently for Cumulus than for the four slash-named vendors

See D3 above: unlike Cisco/Dell/Juniper/SONiC, Cumulus's `swpN` naming carries no slash, so the computed
`index` attribute is expected to render the real port number rather than `000` — the same outcome Arista's
flat `EthernetN` naming already produces. Confirm during implementation rather than assume, consistent with
every prior vendor's treatment of this attribute.
