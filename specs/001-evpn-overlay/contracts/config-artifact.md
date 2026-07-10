# Contract: Rendered `startup_configuration` Artifact

The expanded `transforms/templates/startup_config.j2` produces NX-OS-style config. This contract defines
**which sections appear per device role**. The existing OSPF underlay block is preserved on all devices (now
also advertising the `vtep` loopback on leafs).

## Per-role section matrix

| Section | Leaf | Spine | Super-spine |
|---------|:----:|:-----:|:-----------:|
| OSPF underlay (incl. loopback0 + vtep loopback) | ✅ (vtep) | ✅ | ✅ |
| `feature bgp / nv overlay / vn-segment-vlan-based`, `nv overlay evpn` | ✅ | ✅ | ✅ |
| `router bgp <asn>` + iBGP EVPN neighbors (cabled neighbors) | ✅ | ✅ | ✅ |
| `route-reflector-client` toward lower-tier neighbors | — | ✅ (→leaf) | ✅ (→spine) |
| `interface nve1` (source = vtep loopback1) | ✅ | — | — |
| L2VNI `member vni`, `vlan/vn-segment`, `suppress-arp` | ✅ | — | — |
| L3VNI `member vni … associate-vrf`, `vrf context`, transit SVI | ✅ | — | — |
| Anycast SVI (`interface Vlan<id>`, anycast-gateway) | ✅ (IRB segs) | — | — |

## Leaf overlay block (shape)

```text
router bgp <device.asn>
  router-id <loopback0 ip>
  ! one neighbor per directly-connected neighbor (spines)
  neighbor <spine loopback0> remote-as <device.asn>
    update-source loopback0
    address-family l2vpn evpn
      send-community extended

interface nve1
  source-interface loopback1            ! vtep_ip
  host-reachability protocol bgp
  member vni <l2vni>                     ! per carried segment
    suppress-arp
    ingress-replication protocol bgp
  member vni <l3vni> associate-vrf       ! per carried VRF

vlan <vlan_id>
  vn-segment <l2vni>
vlan <l3_vlan_id>
  vn-segment <l3vni>

vrf context <vrf.name>                   ! per carried VRF (gateway-bearing segments)
  vni <l3vni>
  rd <loopback0 ip>:<l3vni>
  address-family ipv4 unicast
    route-target both <vrf.route_target> evpn

interface Vlan<l3_vlan_id>               ! L3VNI transit/core SVI
  vrf member <vrf.name>
  ip forward

interface Vlan<vlan_id>                  ! anycast gateway, only if segment.gateway present
  vrf member <vrf.name>
  ip address <segment.gateway>
  fabric forwarding mode anycast-gateway

fabric forwarding anycast-gateway-mac <fabric.anycast_gateway_mac | default>
```

## Spine / super-spine overlay block (shape)

```text
router bgp <device.asn>
  router-id <loopback0 ip>
  neighbor <neighbor loopback0> remote-as <device.asn>
    update-source loopback0
    address-family l2vpn evpn
      send-community extended
      route-reflector-client            ! ONLY toward lower-tier neighbors (spine→leaf, super-spine→spine)
```

## Invariants

- A device with no materialized `segments` renders **no** NVE/VLAN/VRF/SVI (guarantees spine/super-spine
  carry no tenant state — FR-007, SC-006).
- An L2-only segment (no `gateway`) renders its `vlan`/`vn-segment`/NVE `member vni` but **no** anycast SVI
  (D5, SC-007).
- Changing a tenant/segment changes only the affected leafs' artifacts (FR-009, SC-003) via materialized
  `Device.segments`.
