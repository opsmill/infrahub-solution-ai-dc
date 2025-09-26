from __future__ import annotations

from typing import TYPE_CHECKING

from solution_ai_dc.protocols import NetworkInterface

if TYPE_CHECKING:
    from infrahub_sdk import InfrahubClient
    from solution_ai_dc.protocols import NetworkDevice

async def set_interface_profiles(client: InfrahubClient, device: NetworkDevice):
    interface_profiles = await client.all("ProfileNetworkInterface")
    profiles_map = {profile.role.value: profile for profile in interface_profiles}

    interfaces = await client.filters(NetworkInterface, device__ids=[device.id], include=["profiles"])

    for interface in interfaces:
        profile = profiles_map.get(interface.role.value)

        if profile is None:
            continue

        interface.profiles.add(profile)
        await interface.save(allow_upsert=True)
        
