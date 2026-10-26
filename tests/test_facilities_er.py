import pytest

from mcp_server.providers import LiveProvider
from mcp_server.server import build_server

CHUNGJU = {"lat": 36.991, "lon": 127.926}


@pytest.mark.asyncio
async def test_free_beds_first_then_nearest(api):
    async with api() as client:
        resp = await client.get("/facilities/er", params=CHUNGJU)
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 3 and body["any_uncertain"] is False
    hvecs = [f["hvec"] for f in body["facilities"]]
    assert hvecs[-1] == 0 and all(h > 0 for h in hvecs[:-1])
    free = [f["distance_km"] for f in body["facilities"] if f["hvec"] > 0]
    assert free == sorted(free)
    assert all(f["source"] == "MOCK" for f in body["facilities"])


@pytest.mark.asyncio
async def test_available_only_drops_full_ers(api):
    async with api() as client:
        body = (await client.get("/facilities/er", params={"available_only": "true"})).json()
    assert body["count"] == 2 and all(f["hvec"] > 0 for f in body["facilities"])


@pytest.mark.asyncio
async def test_stale_data_flagged(api):
    async with api(stale_minutes=200) as client:
        body = (await client.get("/facilities/er")).json()
    assert body["any_uncertain"] is True
    assert {f["status"] for f in body["facilities"]} == {"UNCERTAIN"}


@pytest.mark.asyncio
@pytest.mark.parametrize("params", [{"lat": 36.9}, {"lon": 127.9}, {"lat": 91, "lon": 0}, {"region": ""}])
async def test_bad_query_is_422(api, params):
    async with api() as client:
        resp = await client.get("/facilities/er", params=params)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_provider_failure_is_502(api):
    async with api(failure_rate=1.0) as client:
        resp = await client.get("/facilities/er")
    assert resp.status_code == 502
    assert resp.json()["error"] == "TOOL_ERROR"


@pytest.mark.asyncio
async def test_live_provider_is_502(api):
    async with api(server=build_server(LiveProvider())) as client:
        resp = await client.get("/facilities/er")
    assert resp.status_code == 502
    assert "NOT_IMPLEMENTED" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_timeout_is_504(api):
    async with api(timeout_s=0.1, delay_ms_range=(400, 400)) as client:
        resp = await client.get("/facilities/er")
    assert resp.status_code == 504


@pytest.mark.asyncio
async def test_mcp_down_is_503(api):
    async with api(server="http://127.0.0.1:9/mcp") as client:
        resp = await client.get("/facilities/er")
    assert resp.status_code == 503
    assert resp.json()["error"] == "UNAVAILABLE"


@pytest.mark.asyncio
async def test_hung_mcp_server_is_504_not_a_hang(api, silent_server_url):
    async with api(server=silent_server_url, timeout_s=0.3) as client:
        resp = await client.get("/facilities/er")
    assert resp.status_code == 504
    assert resp.json()["error"] == "TIMEOUT"
