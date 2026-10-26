import pytest
from mcp import Client

from mcp_server.providers import LiveProvider, MockProvider
from mcp_server.server import build_server


def _server(**kwargs):
    return build_server(MockProvider(delay_ms_range=(0, 0), seed=1, **kwargs))


@pytest.mark.asyncio
async def test_lists_three_tools():
    async with Client(_server()) as client:
        names = {t.name for t in (await client.list_tools()).tools}
    assert names == {"get_er_beds", "get_pharmacies", "get_otc"}


@pytest.mark.asyncio
async def test_er_beds_structured_result():
    async with Client(_server()) as client:
        result = await client.call_tool("get_er_beds", {"region": "Chungju", "lat": 36.991, "lon": 127.926})
    assert not result.is_error
    ers = result.structured_content["result"]
    assert len(ers) == 3
    assert all(e["source"] == "MOCK" and e["status"] == "LIVE" for e in ers)
    assert ers[0]["distance_km"] <= ers[-1]["distance_km"]


@pytest.mark.asyncio
async def test_provider_error_becomes_tool_error():
    async with Client(_server(failure_rate=1.0)) as client:
        result = await client.call_tool("get_otc", {"category": "cut"})
    assert result.is_error
    assert "PROVIDER_ERROR" in result.content[0].text


@pytest.mark.asyncio
async def test_live_provider_becomes_not_implemented():
    async with Client(build_server(LiveProvider())) as client:
        result = await client.call_tool("get_er_beds", {"region": "Chungju"})
    assert result.is_error
    assert "NOT_IMPLEMENTED" in result.content[0].text
