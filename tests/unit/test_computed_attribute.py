import pytest
from infrahub_sdk.template import Jinja2Template

INTF_INDEX_JINJA2 = '{{ "%03d"| format(name__value | split_interface | last | int) }}'


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
