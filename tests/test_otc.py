import pytest

from backend.app.schemas.otc import DISCLAIMER


@pytest.mark.asyncio
async def test_cut_returns_generic_items(api):
    async with api() as client:
        resp = await client.get("/otc/cut")
    assert resp.status_code == 200
    body = resp.json()
    assert body["category"] == "cut" and body["call_119"] is False
    assert "Sterile dressing" in body["items"]
    assert body["disclaimer"] == DISCLAIMER


@pytest.mark.asyncio
async def test_critical_calls_119_without_items(api):
    async with api() as client:
        body = (await client.get("/otc/critical")).json()
    assert body == {"category": "critical", "items": [], "call_119": True, "disclaimer": DISCLAIMER}


@pytest.mark.asyncio
async def test_critical_works_even_when_mcp_is_down(api):
    async with api(server="http://127.0.0.1:9/mcp") as client:
        resp = await client.get("/otc/critical")
    assert resp.status_code == 200 and resp.json()["call_119"] is True


@pytest.mark.asyncio
async def test_unknown_category_is_422(api):
    async with api() as client:
        resp = await client.get("/otc/headache")
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_provider_failure_is_502(api):
    async with api(failure_rate=1.0) as client:
        resp = await client.get("/otc/burn")
    assert resp.status_code == 502


@pytest.mark.asyncio
async def test_timeout_is_504(api):
    async with api(timeout_s=0.1, delay_ms_range=(400, 400)) as client:
        resp = await client.get("/otc/fever")
    assert resp.status_code == 504
