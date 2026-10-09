@AGENTS.md

<!-- SPECKIT START -->
Active features:

- EVPN/VXLAN Overlay (`specs/001-evpn-overlay/`)
- Multivendor Per-Vendor Configuration (`specs/002-multivendor-config/`)
- Juniper / Junos Vendor Support (`specs/003-juniper-junos-support/`)
- Server Service — connect L2/L3 servers to leaves (`specs/003-server-service/`)
- Kubernetes Clusters with Cilium BGP — group Server services into a cluster and render its
  Cilium BGP manifest (`specs/004-kubernetes-cilium-bgp/`)
- SONiC Vendor Support (`specs/005-sonic-vendor-support/`)

For technologies, project structure, and design decisions, read each feature's
`plan.md` (and its `research.md`, `data-model.md`, `contracts/`, `quickstart.md`).
Domain language: `CONTEXT.md`; decision rationale: `dev/adr/0001`–`0007`.
<!-- SPECKIT END -->
