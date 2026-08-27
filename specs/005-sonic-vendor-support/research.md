# Phase 0 Research: SONiC Vendor Support

This file records each design decision with rationale and the mechanics that make it implementable, following
the same standard set by `specs/003-juniper-junos-support/research.md` (the fourth vendor added under the
`002-multivendor-config` pattern; this is the fifth). Where a claim was checked against the code in this
repository, that check is stated. Where a claim is about SONiC/FRR itself rather than this codebase, it is
stated as a documented convention to be confirmed by the human reviewer at SC-001, not as something verified
here. No `NEEDS CLARIFICATION` markers remain.

## D1 — Vendor registration: one tuple entry

- **Decision**: Add `"sonic"` to `SUPPORTED_VENDORS` in `src/infrahub_solution_ai_dc/vendors.py`. Nothing else
  in that module changes.
- **Rationale**: `vendor_group_for_manufacturer` derives the group name as
  `f"{name.strip().lower()}_devices"`, so `sonic_devices` follows automatically once the vendor is allowed.
- **Verified mechanic**: `vendors.py:24` is the single allow-list; `vendors.py:45` does the derivation;
  `vendor_group_for_template` walks `TemplateNetworkDevice.device_type → NetworkDeviceType.manufacturer →
  OrganizationManufacturer.name` and delegates to the same function. The three generators
  (`generate_fabric.py`, `generate_pod.py`, `generate_rack.py`) call it once each and stamp
  `member_of_groups=["devices", self.vendor_group]`.
- **Consequence**: **No generator file changes.** This is the direct evidence for spec SC-002, exactly as it
  was for Juniper.

## D2 — "Manufacturer" models the config dialect, not a legal hardware maker

- **Decision**: Add one `OrganizationManufacturer` named `SONiC`. Device types under it are named after
  chipset generation, not a specific ODM's switch model — **revised in D7** from an earlier draft that used
  real Edgecore SKUs; the reasoning below for *why a manufacturer entry at all* is unchanged, only *what the
  device type names* changed.
- **Rationale**: `OrganizationManufacturer.name` is a free-text unique `Text` attribute with no vendor enum
  anywhere in the schema (confirmed by reading `schemas/device.yml` and `schemas/organization.yml` — there is
  no closed list to extend). The four existing entries already conflate "who makes the box" with "which
  config dialect it speaks" — that conflation is what `vendors.py` is built on. SONiC does not make hardware;
  it is an OS that runs on switches from several ODMs. Modelling it as one more manufacturer entry keeps the
  existing pattern intact rather than inventing a second axis (hardware maker vs. OS) that nothing else in
  the data model has.
- **Hardware naming, revised**: an initial pass chose specific Edgecore SKUs for hardware fidelity, reasoning
  that recognisable real model numbers matter to a SONiC-standardised evaluator. That's true of hardware in
  general, but not of *which ODM box* for SONiC specifically — two different vendors' switches built on the
  same chipset behave identically from a SONiC config perspective, so the ODM name doesn't actually carry the
  information a SONiC evaluator would check. D7 revises this to name device types after the chipset
  generation instead (`SONiC-T4`/`T5`/`T6`, `SONiC-TD4`), which is both more accurate to what matters for
  SONiC and avoids needing to pick (and vouch for) any specific ODM's product line.
- **Side effect**: this also resolves the collision concern the Edgecore choice was originally solving for —
  `NetworkDeviceType.uniqueness_constraints` is `[manufacturer, name__value]` per `schemas/device.yml:38-39`,
  so a same-named device type under a different manufacturer would be schema-legal but confusing in the UI.
  With no ODM box name in play at all, there is nothing left to collide with.
- **Alternative considered**: Reuse the exact Dell model numbers already in this repo (Dell explicitly ships a
  SONiC image for some of the same PowerSwitch SKUs used for Dell OS10 here) under a new `SONiC` manufacturer.
  Rejected for the same UI-confusion reason above, and superseded by the chipset-naming approach regardless —
  two device types sharing an identical model name under different manufacturers
  reads as a data error in the UI, not as the intended "same box, different OS" story it would actually be
  telling.

## D3 — Interface naming: SONiC's alias (front-panel) convention, and it is safe

- **Decision**: Use SONiC's **alias** interface-naming mode — `Eth1/N`, where `N` is the sequential front-panel
  port number (port 1 → `Eth1/1`, port 2 → `Eth1/2`, port 3 → `Eth1/3`, …) — rather than the default mode's
  lane-indexed `EthernetN` (port 1 → `Ethernet0`, port 2 → `Ethernet4`, …). Both are real, officially supported
  SONiC naming modes (`config interface_naming_mode {default|alias}`); alias mode is the front-panel-friendly
  form most operators actually configure, precisely because the default mode's per-lane numbering is
  considered unreadable. None of the SONiC hardware chosen here (D7) is modelled with breakout, so a port is
  always `Eth1/N` — no third (lane) segment.
- **Revised from an earlier draft**: an initial pass used the default mode's lane-indexed `EthernetN` naming.
  That is also real SONiC behaviour, but it is **sequential-only within groups of 4** rather than truly
  sequential, which meant every port group had to be written out as an explicit comma list (see the
  superseded D10 below) — correct, but it produced YAML lines that violate this repository's 140-character
  yamllint limit for anything beyond a handful of ports. Alias mode avoids that entirely, is at least as
  authentic to what an evaluator would recognise (arguably more so, since it is the form shown in SONiC's own
  documentation and `show` output by default in many deployments), and needs no workaround.
- **Risk investigated**: like Dell (`Ethernet1/[1-64]`) and unlike Juniper (two interface-name *families*),
  SONiC keeps every port inside a single `Eth1/` family; the risk is purely numeric-vs-lexicographic ordering
  (`Eth1/10` sorts before `Eth1/2` under a naive string sort).
- **Verified safe**: cabling and rendering order both go through
  `create_sorted_device_interface_map`/`create_reverse_sorted_device_interface_map`
  (`src/infrahub_solution_ai_dc/sorting.py`), which delegate to `netutils.interface.sort_interface_list` — a
  numeric-aware sorter, not a string sort. `Ethernet1/[1-32]` (Dell) and `DellS5232FLeafSwitchEthernet1/1/[1-16]`
  already rely on the exact same slash-delimited numeric form; `Eth1/N` is not a new case for it.
- **Alternatives considered**: the default mode's lane-indexed `EthernetN` naming (superseded, see above);
  vendor-neutral sequential numbering with no SONiC-specific prefix — rejected for the same reason Juniper
  rejected vendor-neutral names in D2: it is the detail a SONiC engineer would notice is wrong.

## D4 — Loopbacks: vendor-neutral names, mapped in-template (unchanged from D4 in 003)

- **Decision**: Object templates declare `Loopback0` (role `loopback`); the VTEP loopback stays `Loopback1`
  (role `vtep`), created at runtime by `generate_rack.py`/`addressing.py` exactly as for every other vendor.
  The SONiC template maps them to the SONiC loopback interface (`Loopback0`, SONiC's own convention keeps the
  literal name `Loopback0` for the routing-protocol loopback — no rename needed) and to the VTEP source
  address consumed by `config vxlan add`.
- **Rationale**: Reuses the same design `003` established: `addressing.py`'s hardcoded `Loopback1` and the
  generators stay vendor-blind; interface **role** is the reliable discriminator, not the literal name.
  Nothing here is SONiC-specific enough to justify a deviation.
- **Consequence**: No change to `addressing.py`, `generate_rack.py`, or `CONTEXT.md`'s existing "vendor group /
  VTEP / role is the discriminator" language — it already describes SONiC's case correctly.

## D5 — SONiC config: two flat syntaxes in one artifact, not one hierarchical block

- **Decision**: Render SONiC's configuration as one flat text artifact combining two distinguishable command
  syntaxes, in two clearly separated sections:
  1. **SONiC `config` CLI** (Linux/Click-CLI style, one command per line) for interfaces, VLANs, and the VXLAN
     tunnel/VLAN-to-VNI map — e.g. `config interface ip add <if> <addr>`, `config vlan add <id>`, `config vlan
     member add <id> <if>`, `config vxlan add vtep1 <src-ip>`, `config vxlan evpn_nvo add nvo1 vtep1`, `config
     vxlan map add vtep1 <vlan-id> <vni>`.
  2. **FRR routing configuration** (`vtysh`-style, e.g. `router bgp <asn>`, `address-family l2vpn evpn`,
     `neighbor <ip> remote-as <asn>`, `neighbor <ip> activate`) for the underlay and EVPN control plane — the
     routing daemon SONiC uses for BGP, including the EVPN address family.
- **Rationale**: This is **not** a hierarchical-bracing risk the way Junos was (D5 in `003`). FRR's CLI
  deliberately mirrors Cisco/Arista-style flat CLI syntax (`router bgp` / `address-family` / `neighbor ...
  remote-as`), so the BGP/EVPN section of the SONiC template is structurally close to the existing Arista
  template's `router bgp` block, not to Junos's `{ }` nesting. The two syntaxes sit side by side in one file,
  consistent with the "startup configuration" framing the other four artifacts already use — there is no
  single unified CLI a real SONiC device boots from, so this is the closest honest single-artifact
  representation.
- **Structural risk, correctly scoped**: the actual risk is a template emitting a `config` CLI verb where an
  FRR verb belongs (or vice versa) — a wrong-dialect line, the same *class* of risk the three flat vendors
  already carry, not a new *kind* of risk. Revise the spec's edge-case framing accordingly: SONiC's failure
  mode is "wrong syntax in the wrong section," not "unbalanced structure," now that the interface-family risk
  from D3 is resolved.
- **Alternative considered**: render only `config_db.json` (SONiC's actual declarative source of truth,
  consumed by `config load` / rendered by `sonic-cfggen`). Rejected for a reference solution: it is JSON, not
  a "configuration a network engineer reads," and it would be the only artifact of the five that isn't a
  human-readable CLI dialect — breaking the "recognisably correct on inspection" framing SC-001 depends on.

## D6 — No automated template validation

- **Decision**: Ship with **no** configuration-template test, golden file, or SONiC/FRR config parser.
  Correctness is established by human review (spec SC-001), exactly as for the four existing vendors.
- **Rationale**: Consistent with `003`'s D6. None of the four existing templates has a template test; the
  repo's only artifact-level test does byte-comparison before/after a change and never inspects content.
- **Mitigation**: SC-001 puts a reviewer with production SONiC/FRR experience on the critical path, with a
  scoped mandate — the `config`-CLI/FRR split and EVPN/VXLAN structure only. Management addressing, MTU and
  operational services are known repo-wide simplifications shared by every vendor and are explicitly outside
  the review, matching `003`'s precedent exactly.

## D7 — Hardware: chipset-generation device types, not ODM box models

- **Decision (revised)**: Model spine/super-spine hardware as **three chipset-generation device types** —
  `SONiC-T4` (Broadcom Tomahawk4), `SONiC-T5` (Tomahawk5), `SONiC-T6` (Tomahawk6) — rather than one specific
  ODM's box model. Leaf hardware is `SONiC-TD4` (Broadcom Trident4-class), a single generation.
- **Why the revision**: for SONiC specifically, the chipset generation — not which ODM's chassis it ships
  in — is what actually determines a device's forwarding capacity, port speed and lane/breakout options.
  Two different vendors' boxes built on the same Tomahawk5 die behave identically from a SONiC config
  perspective; two different-generation boxes from the *same* ODM do not. Naming the device type after the
  chipset rather than a specific SKU models the thing that is actually load-bearing, and, as a side effect,
  fully resolves the earlier D2 concern about a device-type name colliding with an existing vendor's model
  number — there is no ODM box name left to collide.
- **Capacity table** (64-port radix held constant across generations, so the existing spine/super-spine
  template shape — `Eth1/[1-32]` / `Eth1/[33-64]` / `Eth1/[1-64]` — needs no change per generation, only the
  `device_type` reference does):

  | Device type | Chipset | Switching capacity | Ports (modeled) |
  |---|---|---|---|
  | `SONiC-T4` | Tomahawk4 | 25.6 Tbps | 64× 400G |
  | `SONiC-T5` | Tomahawk5 | 51.2 Tbps | 64× 800G |
  | `SONiC-T6` | Tomahawk6 | 102.4 Tbps | 64× 1.6T |

  These capacity/port-speed figures are Broadcom's own publicly stated generational numbers, not invented.
  **Maturity caveat**: Tomahawk6 is materially newer than the other two — 102.4 Tbps was only recently
  announced industry-wide — so `SONiC-T6` is modelled as the forward-leaning entry, not as an equally
  long-shipping, field-proven generation the way T4 is. This is stated plainly rather than smoothed over,
  consistent with this feature's general practice of not overclaiming hardware maturity.
- **Leaf**: `SONiC-TD4` (48× 10/25G SFP28 access + 6× 40/100G QSFP28 uplink) — same port shape as the
  originally-chosen AS7326-56X, renamed for the same chipset-not-box reasoning, single generation since only
  the Tomahawk (spine-class) line was asked to vary.
- **The 6-vs-4 uplink question**: pods default to `amount_of_spines: 4` (`schemas/logical_design.yml:104`),
  same as every other fabric. `SONiC-TD4` genuinely has 6 uplink ports. Cabling takes
  `src_interfaces[:dst_device_count]` (`cabling.py`), so 2 of the 6 uplinks per leaf go uncabled — rendered
  present-but-disabled, exactly as Juniper's surplus uplinks already are and as every vendor's uncabled
  access ports already are.
- **Chipset/breakout-lane fact, now varies per generation**: see D11, revised — T4 is 4-lane, T5 and T6 are
  8-lane. Still documentation only, not modelled as data (D11's core conclusion is unchanged by having three
  generations instead of one).
- **Where each generation is used**: see D8 — one generation per Fabric-E pod, not one generation used and
  two left uncabled in the catalog.

## D11 — Breakout lane count is chipset-dependent (4 or 8, per generation); not modeled, still not load-bearing

- **Finding**: the number of SerDes lanes a breakout-capable port exposes is set by the ASIC generation —
  **4 lanes** for Tomahawk4 (`SONiC-T4`, 400G ports on 4×100G-PAM4 lanes) and for the Trident4-class leaf
  chip (`SONiC-TD4`, 100G uplinks on 4×25G-NRZ lanes); **8 lanes** for Tomahawk5 and Tomahawk6 (`SONiC-T5`,
  `SONiC-T6` — 800G and 1.6T ports respectively, both built on 8-lane SerDes, T6 at a higher per-lane rate).
  Now that this feature models all three Tomahawk generations (D7, revised), both lane counts are actually
  in play, not just theoretical.
- **Consequence for this feature: still none.** D3's alias-mode naming numbers front-panel ports sequentially
  (`Eth1/1`, `Eth1/2`, …) with no breakout sub-port suffix, and none of the three chosen device types is
  modeled with breakout enabled in this fabric. Lane count is therefore never read, computed, or branched on
  anywhere in this design, for any of the three generations — confirmed by the final template shape
  (data-model.md §4): every interface declaration is a plain `Eth1/[a-b]` range, identical in form across
  `SONiC-T4`/`T5`/`T6`, independent of the underlying lane count. This is a direct, incidental benefit of
  moving off the lane-indexed default naming mode in D3: an earlier draft's `i*4` generation formula
  (superseded D10) silently assumed 4 lanes everywhere and would have been wrong for T5/T6, without anything
  surfacing the assumption — now doubly relevant, since T5 and T6 are both actually being modeled.
- **Where it would matter, if breakout is ever modeled**: a breakout sub-port's alias name carries a third
  segment (`Eth1/1/1` … `Eth1/1/4` on `SONiC-T4`/`SONiC-TD4`, `Eth1/1/1` … `Eth1/1/8` on `SONiC-T5`/`SONiC-T6`).
  Lane count is a fact attached to the **physical port**, not to the manufacturer or even the device type as
  a whole — a single device type can mix breakout-capable and fixed-form ports (`SONiC-TD4`'s SFP28 access
  ports are not breakout-capable at all, while its QSFP28 uplinks are). Recording it as real, queryable data
  (e.g. on `NetworkDeviceType` or a per-port-group concept) would be a schema change, out of scope for this
  feature's SC-002 constraint — and no existing vendor in this repo models breakout today either, so it would
  be its own feature with its own spec, not a rider on this one.
- **What to do about it here**: record it as a plain inline comment next to each of the four device-type
  entries in `objects/03_device_type.yml`, matching this repo's existing convention (every device type
  already carries a `# Vendor Model (port count/speed) — role` comment). That gives a future
  breakout-modeling effort a correct, chipset-verified starting fact per generation instead of a guess, at
  zero cost — no schema change, no data attribute, no code.

## D8 — Demo data: full Fabric-E, all three chipset generations shown together, inside the P1 slice

- **Decision**: Ship Fabric-E (SONiC) mirroring Fabric-D's structure — 4 super-spines, Pod-E1 (`role:
  fabric`) / Pod-E2 / Pod-E3, and 8 racks in a hall alongside the existing fabrics — plus one overlay tenant
  scoped to Fabric-E with a gateway-bearing segment and an L2-only segment, matching FR-011. **Revised**: the
  three device types from D7 are not just catalog entries — each of Fabric-E's three pods is built from a
  *different* chipset generation, so all three are actually present and interoperating in the rendered demo,
  not just declared and left unused:

  | Pod | Role | Device type |
  |---|---|---|
  | Pod-E1 | super-spine | `SONiC-T6` (newest silicon at the aggregation layer) |
  | Pod-E2 | spine | `SONiC-T4` (most established generation) |
  | Pod-E3 | spine | `SONiC-T5` (mid-generation) |

  This tells a realistic, relatable operational story — an aggregation layer already upgraded to newer
  silicon while spine layers are still running proven, previous-generation gear — rather than an arbitrary
  assignment, and it means an evaluator sees all three generations at once instead of picking one pod
  arbitrarily and never noticing the other two device types exist.
- **Why this doesn't complicate the config-rendering side**: the SONiC template has no chipset-specific
  logic — every field it consumes (interface role, status, IP, BGP session, segment) is identical in shape
  regardless of which of the three device types produced the interface. Mixing generations within one fabric
  is a topology/data decision only; it does not touch `startup_config_sonic.j2` or the shared query.
- **Rationale**: A vendor capability with no fabric exercising it is invisible to the evaluator and, with no
  template tests (D6), unverifiable — the demo fabric is both the deliverable and the test harness, exactly
  as `003`'s D8 reasoned for Juniper. The same logic extends to the three device types: one used and two
  sitting unexercised in `objects/03_device_type.yml` would be just as invisible as no fabric at all.
- **Verified mechanic**: `generate_fabric.py`'s `allocate_resource_pools` carves a per-fabric `/16` from the
  shared supernet pool and allocates the overlay ASN from a pool keyed by fabric id — Fabric-E needs no manual
  addressing or ASN, exactly as Fabric-D did not. This is unaffected by which device type each pod's
  `*_switch_template` points at — addressing is per-fabric, not per-device-type.
- **Cost**: proportionate to Fabric-D's addition (~+23 devices, ~+30% on top of the post-Juniper demo size).
  Mixing three device types across the existing three pods adds **zero** extra devices — it changes which
  templates Pod-E1/E2/E3 already reference, not how many devices each produces. No load-time or resource
  ceiling has been specified or measured, consistent with `003`'s Assumptions.

## D9 — The existing negative test will need a genuinely-unsupported example

- **Finding**: `tests/unit/test_vendors.py` exercises `SUPPORTED_VENDORS` both for the happy path
  (parametrized, so it already extends with no edit once `"sonic"` is added — same as `003`'s note on
  `test_every_supported_vendor_resolves`) and for the rejection path, which must keep using a manufacturer
  that stays unsupported. `003` re-pointed this test from `"Juniper"` to `"Nokia"` when Juniper was added;
  confirm at implementation time that `"Nokia"` (or whatever the current negative example is) is still not in
  `SUPPORTED_VENDORS` after this change — it will still not be, since only `"sonic"` is being added.
- **Action**: Add a SONiC happy-path case (`("SONiC", "sonic_devices")`) to the parametrized test; no change
  needed to the negative-path fixture.

## D10 (superseded by D3) — Range expansion for alias naming: plain consecutive ranges, verified live

- **Superseded**: D10 originally worked around the lane-indexed default naming mode with explicit comma
  lists. D3 now uses alias-mode sequential naming instead, which needs no workaround — the existing
  `[a-b]` consecutive-range form (already used by every other vendor's templates) covers it directly. This
  section is kept, in reduced form, only to record that the switch was verified rather than assumed.
- **Verified**: `infrahub_sdk.spec.range_expansion.range_expansion` expands `Eth1/[1-64]`,
  `Eth1/[1-32]`, `Eth1/[33-64]`, `Eth1/[1-48]` and `Eth1/[49-54]` exactly as it already expands
  `Ethernet1/[1-64]` for Dell — same bracket form, same slash-delimited numeric suffix — confirmed by
  inspecting `_char_range_expand`'s numeric branch, which is naming-convention-agnostic. No code change, no
  generated comma list, and no line-length concern: every one of these patterns is a two-number bracket
  expression regardless of how many ports it covers, exactly like Juniper's `et-0/0/[0-63]` (research.md D3
  in `003-juniper-junos-support`).
- **Consequence**: the yamllint line-length risk this section originally raised does not apply to the
  alias-mode design. No chunking, no multi-entry workaround needed.

## D12 — Automated guard for device-template wiring (critique E2, retargeted)

- **Origin**: the pre-implementation critique (`critiques/critique-20260827-081053.md`, E2/X2) flagged that
  nothing catches a transcription error in the generated interface-range lists. D3's later pivot to alias-mode
  naming (`Eth1/[1-32]`, a two-number range) removed most of that specific risk — there's very little left to
  transcribe wrong in a two-number bracket. The recommendation is retargeted rather than dropped, because D7's
  later revision (three chipset generations, eight device templates instead of four) introduced a different,
  real risk in the same neighbourhood: **wiring**, not **range syntax**.
- **Decision**: add a small unit test asserting, for all eight SONiC device templates in
  `objects/06_device_template.yml`:
  1. each template's `device_type` matches the intended chipset/role pairing (e.g.
     `sonic-t6-super-spine-switch` → `["SONiC", "SONiC-T6"]`, not an accidentally-copy-pasted `SONiC-T4`);
  2. each template's interfaces expand (via `infrahub_sdk.spec.range_expansion.range_expansion`) to the
     expected count and first/last interface name — 65 for every spine/super-spine template regardless of
     generation, 55 for both leaf templates.
- **Rationale**: eight templates that are meant to be near-identical copies differing only in
  `template_name`/`device_type` (data-model.md §4) are exactly the shape of change most likely to suffer a
  silent copy-paste error — declare a T5 template but leave its `device_type` pointing at `SONiC-T4`, and
  nothing before this test would catch it; the rendered config would look fine (same shape, wrong provenance)
  and only a very close read of the object data would notice.
- **Where**: a new `tests/unit/test_sonic_device_templates.py`, or an addition to `tests/unit/test_vendors.py`
  if a shared fixture makes more sense at implementation time — either satisfies D12; the assertion content is
  what matters, not the file split.
- **Scope boundary preserved**: this does not contradict D6 (no automated *rendered-config* test). It asserts
  object-data shape, a surface D6 never covered — the same distinction Scenario 1 in `quickstart.md` already
  draws when checking interface counts, just made automatic instead of manual.

## D13 — Two implementation-time defects, caught by synthetic render before commit

The chunk that implemented T009-T017 produced a first draft of `startup_config_sonic.j2` that parsed cleanly
but had two defects only a rendered (not just parsed) output against representative data would surface.
Neither was caught by `inv lint` (syntax/style only) or the template's own author, and no template test exists
to catch them automatically (D6) — both were found by a synthetic Jinja2 render against hand-built mock
GraphQL data (two devices: a leaf with a mixed EVPN + attached-server session, and a spine) before commit.

- **Defect 1 — the interface loop leaked `Loopback1` as a literal interface.** The `config` CLI per-interface
  loop was unfiltered by role for the description/admin-state lines (only the `ip add` line was role-gated),
  so it rendered `config interface description Loopback1 ...` / `config interface shutdown Loopback1` for the
  `vtep`-role interface — directly violating the contract's own "never name the VTEP loopback as a literal
  interface" rule (§ Structural rule). Fixed by excluding `loopback`/`vtep` roles from the whole per-interface
  block, not just its `ip add` line.
- **Defect 2 — no `ipv4_unicast` vs. EVPN session split.** The FRR neighbor loop treated every
  `device.bgp_sessions.edges` entry as an EVPN peer to another device's loopback. A leaf with an attached L3
  server (`ServerGenerator`, eBGP to the server's `/31`) has an `ipv4_unicast` session whose peer is a
  `NetworkServer`, which does not expose `loopback_ip` — every other vendor's template (Arista, Juniper,
  Cisco, Dell) already splits sessions by `address_family` for exactly this reason; the SONiC contract's
  Data surface table omitted `address_family` entirely, and the template followed the contract's omission.
  Fixed in both the template (`evpn_sessions`/`ipv4_sessions` split, mirroring Arista/Juniper's pattern, plus
  a new `address-family ipv4 unicast` block) and the contract (`contracts/sonic-config-contract.md`, Data
  surface table and the FRR EVPN control-plane section).
- **Two smaller additions made at the same time**: `neighbor ... send-community extended` on EVPN sessions
  (FRR-standard for route-target propagation, already present in the Arista template; the first draft omitted
  it) and an explicit `exit-address-family` before the tenant-overlay FRR block's final `exit` (consistency
  with the main EVPN block's own pattern; FRR's exact context-exit semantics here were not independently
  verified against a live `vtysh` session, so this is a defensible improvement, not a fully verified fix —
  flag for the SC-001 reviewer alongside the pre-existing verb-precision caveats every other decision in this
  file already carries).
- **One deliberate non-fix**: the first draft's anycast-gateway-MAC normalisation (copied from the preamble
  convention the other four templates use) was never actually consumed anywhere in the required output — a
  gap in the contract, not the template. Rather than invent unverified SONiC Static Anycast Gateway (SAG)
  syntax under uncertainty, the dead computation was removed and the gap recorded explicitly in the contract's
  Out of Scope list, flagged as a genuine fidelity gap relative to Arista/Juniper (not a neutral simplification
  shared by all five vendors) for the SC-001 reviewer to weigh in on.
- **Verification method**: a synthetic render (not `inv lint`, not a live Infrahub stack — Docker is
  unavailable in the implementation sandbox) using hand-built mock data matching the shared query's exact
  field shape, covering the specific case (mixed session types on one leaf) most likely to expose Defect 2.
  Both the leaf and a spine device rendered without error after the fixes; output was inspected against every
  acceptance rule (A1-A8) in the contract. This is not a substitute for D6's declined automated template test
  — it is a one-time manual check performed during implementation, the same kind of check D6 explicitly
  chose not to make repeatable.
- **Two further defects, caught by an independent multi-agent review pass after commit** (three review
  agents — code quality, test-coverage, silent-failure analysis — run against the full diff): (3) the
  tenant-overlay FRR block reopened `router bgp {{ overlay_asn }}` with no `overlay_asn is not none` guard
  of its own, unlike the underlay/EVPN block — currently unreachable in practice (`generate_tenant.py` only
  materialises segments once the overlay ASN is resolved), but the template had no defence of its own against
  stale/partial data; fixed by nesting the whole FRR tenant-overlay block inside that guard. (4) the VXLAN
  tunnel-source line (`config vxlan add vtep1 {{ vtep.addr }}`) would silently render with a missing address
  argument if a leaf had segments but no addressed `vtep`-role interface — `generate_rack.py` treats VTEP
  assignment as best-effort and can skip it when a pod's `vtep_pool` is unset, so this is reachable by
  construction even though not exercised by Fabric-E's current demo data; fixed by rendering a loud
  `! ERROR: no addressed vtep-role interface found ...` comment instead of the malformed command when no
  address is found, rather than failing silently. Both fixes re-verified by re-running the synthetic render
  plus a new edge-case render (no `overlay_asn`, no `vtep`-role interface, segments present) confirming
  neither `router bgp` nor a malformed `vxlan add` line leaks into the output. The same review also flagged
  three test-coverage gaps in `test_sonic_device_templates.py` (D12) — the per-template `role` field, each
  interface range's `profiles`, and the `interfaces.parameters.expand_range` flag were all declared but never
  asserted, meaning a copy-paste error in any of them would have left every test green — closed by extending
  the test's expected-value tables and adding two more parametrized assertions.

## Cross-cutting: what does not change

Confirmed by inspection, and asserted as spec SC-002:

- **No schema change.** No vendor enum anywhere in `schemas/`; `OrganizationManufacturer.name` is free-text.
  `protocols.py` is therefore **not** regenerated.
- **No generator change.** Vendor resolution already runs in all three generators via `vendors.py`.
- **No GraphQL change.** `transforms/startup_config.gql` already returns every field every vendor's template
  needs — interfaces (name/description/role/status/ip), BGP sessions, segments, VRF — and the SONiC template
  needs nothing beyond that set.
- **No new dependency, no CI change, no auth change.**

## Note carried forward from `003`, applies identically to SONiC

The computed `index` attribute (`schemas/device.yml:207`,
`{{ "%03d"| format(name__value | split_interface | last | int) }}`) renders `000` for every Cisco, Dell and
Junos interface today, because `split_interface` leaves a slash-bearing remainder that Jinja's `int` filter
cannot parse. SONiC's alias-mode `Eth1/N` names (D3) **do** carry a slash, so this attribute is expected to
render `000` for SONiC interfaces too — the same pre-existing, vendor-wide, out-of-scope behaviour as
Cisco/Dell/Juniper, not the exception Arista's flat names are. (An earlier draft of D3 used the slash-free
default naming mode, which would have behaved like Arista instead — recorded here only so the discrepancy
between draft and final decision doesn't resurface as a false expectation.) Recorded because
`NetworkInterface.order_by: ["index__value"]` depends on the attribute. Confirm during implementation rather
than assume, consistent with `003`'s treatment of the same attribute.
