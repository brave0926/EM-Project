import re

import pytest

STATION = {"lat": 36.972, "lon": 127.900}


@pytest.mark.asyncio
async def test_open_at_2am_nearest_first(api):
    async with api() as client:
        resp = await client.get("/facilities/ph", params=STATION | {"at_time": "02:00"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["at_time"] == "02:00"
    assert [f["name"] for f in body["facilities"]] == [
        "Station Night Pharmacy (mock)",
        "Yeonsu Central Pharmacy (mock)",
    ]
    assert body["count"] == 2 and body["any_uncertain"] is False


@pytest.mark.asyncio
async def test_closed_pharmacies_filtered_at_5am(api):
    async with api() as client:
        body = (await client.get("/facilities/ph", params=STATION | {"at_time": "05:00"})).json()
    assert [f["name"] for f in body["facilities"]] == ["Yeonsu Central Pharmacy (mock)"]


@pytest.mark.asyncio
async def test_default_time_is_reported(api):
    async with api() as client:
        body = (await client.get("/facilities/ph", params=STATION)).json()
    assert re.fullmatch(r"\d\d:\d\d", body["at_time"])


@pytest.mark.asyncio
async def test_stale_data_flagged(api):
    async with api(stale_minutes=200) as client:
        body = (await client.get("/facilities/ph", params=STATION | {"at_time": "12:00"})).json()
    assert body["count"] > 0 and body["any_uncertain"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "params",
    [{"lat": 36.97}, {"lon": 127.9}, STATION | {"at_time": "25:00"}, STATION | {"at_time": "2am"}],
)
async def test_bad_query_is_422(api, params):
    async with api() as client:
        resp = await client.get("/facilities/ph", params=params)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_provider_failure_is_502(api):
    async with api(failure_rate=1.0) as client:
        resp = await client.get("/facilities/ph", params=STATION)
    assert resp.status_code == 502
