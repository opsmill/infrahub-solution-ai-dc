import pytest
from infrahub_sdk.template import Jinja2Template

INTF_INDEX_JINJA2 = '{{ "%03d"| format(name__value | split_interface | last | int) }}'

# NetworkServer.node_selector (schemas/server.yml) — kept byte-identical to the schema's
# computed_attribute.jinja2_template so this test pins the shipped template, not a copy of it.
NODE_SELECTOR_JINJA2 = '{{ hostname__value | replace("server-", "", 1) }}'


@pytest.mark.parametrize(
    "intf_name,expected",
    [
        ("Ethernet12", "012"),
        ("Ethernet4", "004"),
    ],
)
async def test_intf_index(intf_name: str, expected: str) -> None:
    tpl = Jinja2Template(template=INTF_INDEX_JINJA2)
    rendered = await tpl.render(variables={"name__value": intf_name})
    assert rendered == expected


@pytest.mark.parametrize(
    "hostname,expected",
    [
        # FR-002: the node selector is the hostname minus the generator's ``server-`` prefix
        # (generate_server.py's ``server_hostname`` builds ``f"server-{service_name}"``).
        ("server-cilium-worker-1", "cilium-worker-1"),
        ("server-web-host-1", "web-host-1"),
        # The count-limited replace is deliberate: a service legitimately named ``server-side-cache``
        # must keep its inner occurrence. An unanchored replace would yield "side-cache".
        ("server-server-side-cache", "server-side-cache"),
        # A hostname without the prefix is passed through untouched rather than mangled.
        ("cilium-worker-1", "cilium-worker-1"),
    ],
)
async def test_node_selector(hostname: str, expected: str) -> None:
    tpl = Jinja2Template(template=NODE_SELECTOR_JINJA2)
    rendered = await tpl.render(variables={"hostname__value": hostname})
    assert rendered == expected
