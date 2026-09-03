# Spec/Ask Alignment Check: NVIDIA Cumulus Linux Vendor Support

**Date**: 2026-09-02

## Source

Inline user ask (no URL) provided to `speckit-opsmill-prep`/`speckit-specify`, ~1,900 characters, a single
substantive paragraph (exceeds the >400-character threshold for running this check):

> "Add NVIDIA Cumulus Linux as a new supported network device vendor, following the exact pattern established
> by 002-multivendor-config and exercised end-to-end by 005-sonic-vendor-support (the immediately preceding
> vendor addition). Scope: add cumulus to the supported-vendors list, create a new startup-config template for
> Cumulus Linux's device syntax (ifupdown2-style /etc/network/interfaces bridge/VXLAN provisioning for the
> data plane, plus FRR for the EVPN/BGP control plane -- the same two-syntax split precedent SONiC
> established), register a Cumulus config transform and artifact definition targeting a new cumulus_devices
> group, add Cumulus manufacturer/device-type/device-template object data using real NVIDIA
> Spectrum-ASIC-based switch models (spanning multiple Spectrum chipset generations across
> spine/super-spine/leaf tiers, matching the breadth SONiC modelled across Tomahawk generations), and add a
> demo fabric/rack (plus a scoped overlay tenant with at least one gateway-bearing and one L2-only segment) so
> the new vendor is visible and inspectable end-to-end. No schema changes and no generator changes should be
> needed -- if either turns out to be necessary, that's a finding to flag, not something to silently do.
> Adding Cumulus MUST NOT alter the behaviour of the existing Cisco, Arista, Dell, Juniper or SONiC fabrics or
> their rendered configurations."

## Verdict

✅ **ALIGNED**

## Findings

| Severity | Category | Ask reference | Spec reference | Description |
|---|---|---|---|---|
| — | — | — | — | No drift found. |

Every element of the ask maps directly onto the spec, with no unexplained additions and no drops:

| Ask element | Spec coverage |
|---|---|
| Add Cumulus, follow 002/005 pattern | Title, Input, User Story 1 framing |
| Add `cumulus` to supported-vendors list | FR-001, FR-002 |
| New startup-config template, ifupdown2 `/etc/network/interfaces` + FRR two-syntax split (SONiC precedent) | Edge Cases ("Cumulus Linux configuration is split across two distinct syntaxes"), Assumptions ("Overlay model") |
| Register transform + artifact definition targeting `cumulus_devices` | FR-001, FR-004, FR-006 |
| Manufacturer/device-type/device-template data on real NVIDIA Spectrum ASIC models, spanning generations across spine/super-spine/leaf, matching SONiC's breadth | Key Entities (Device Type, Device Template), Assumptions ("Switch models chosen") |
| Demo fabric/rack + scoped tenant with gateway-bearing and L2-only segments | FR-009, FR-011, User Story 1, Independent Test |
| No schema/generator changes; flag if either becomes necessary | SC-002, Out of Scope |
| Must not alter Cisco/Arista/Dell/Juniper/SONiC behaviour | FR-010, SC-003 |

The spec adds implementation-adjacent detail beyond the ask (specific device-type names, exact port counts,
the `swp` interface-naming convention, the tenant/VRF/segment names) — this is expected elaboration of an
intentionally scope-and-pattern-focused ask, not scope drift, matching the same latitude
`005-sonic-vendor-support`'s spec took relative to its own equivalently-shaped ask.

## Action

Proceed. No remediation pass required.
