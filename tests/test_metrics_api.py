"""GET /metrics after triage and stream calls (offline: in-process em-mcp-server or a fake client)."""

import asyncio
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from backend.app.clients.mcp_client import McpClientError, set_mcp_client
from backend.app.main import app
from backend.app.models.domain import ERFacility, Location, PharmacyFacility

AMBER = "Severe burn on my hand, near Chungju Station, 2 AM"
RED = "He is unconscious, not breathing"
SECRET = "Zyxwvut-unique-phrase"
FETCHED = datetime.now(timezone.utc) - timedelta(minutes=5)


def contract(body, cid, metric):
    return next(c for c in body["contracts"] if c["contract"] == cid and c["metric"] == metric)


async def get_metrics(client: httpx.AsyncClient) -> dict:
    response = await client.get("/metrics")
    assert response.status_code == 200
    return response.json()


@pytest.mark.asyncio
async def test_empty_metrics_are_zeros(api):
    async with api() as client:
        body = await get_metrics(client)
    assert body["window"] == 0 and body["requests_total"] == 0 and body["fallback_served"] == 0
    assert [c["count"] for c in body["contracts"]] == [0, 0, 0, 0, 0]
    assert set(body["breakers"]) == {"er", "pharmacy"}


@pytest.mark.asyncio
async def test_triage_and_stream_are_counted(api):
    async with api() as client:
        assert (await client.post("/api/triage", json={"query": AMBER})).status_code == 200
        assert (await client.post("/api/triage", json={"query": RED})).status_code == 200
        stream = await client.post("/api/triage/stream", json={"query": f"{AMBER} {SECRET}"})
        assert stream.status_code == 200 and "event: done" in stream.text
        body = await get_metrics(client)

    assert body["window"] == body["requests_total"] == 3
    assert body["by_kind"] == {"triage": 2, "stream": 1}
    assert body["by_severity"] == {"red": 1, "amber": 2, "green": 0}
    assert body["by_source"] == {"MOCK": 3} and body["fallback_served"] == 0
    assert contract(body, "RT-101", "ttft_ms")["count"] == 1  # stream only
    assert contract(body, "RT-101", "ttft_ms")["ok_rate"] == 1.0
    assert contract(body, "RT-102", "er_ms")["count"] == 3  # the graph's worker tasks saw the request timing
    assert contract(body, "RT-102", "pharmacy_ms")["count"] == 2  # RED skips the pharmacy
    total = contract(body, "RT-105", "total_ms")
    assert total["count"] == 3 and total["ok_rate"] == 1.0 and total["p50_ms"] <= total["p95_ms"] <= total["max_ms"]
    text = str(body)
    assert SECRET not in text and "burn" not in text.lower() and "36.97" not in text  # no user text or place


class FlakyMcp:
    """Answers, then fails every call once `down` is set (UNAVAILABLE)."""

    def __init__(self) -> None:
        self.down = False

    async def _answer(self, value):
        if self.down:
            raise McpClientError("UNAVAILABLE", "cannot connect to em-mcp-server")
        await asyncio.sleep(0)
        return value

    async def get_er_beds(self, region, near=None):
        return await self._answer([ERFacility(name="ER", location=Location(name="a", lat=36.98, lon=127.93), hvec=2,
                                              tel="043-000-0000", fetched_at=FETCHED, source="LIVE", distance_km=1.0)])

    async def get_pharmacies(self, near, at_time=None):
        return await self._answer([PharmacyFacility(name="Ph", location=Location(name="b", lat=36.97, lon=127.9),
                                                    open_until="04:00", tel="043-000-0001", fetched_at=FETCHED,
                                                    source="LIVE", distance_km=0.3)])

    async def get_otc(self, category):
        return ["Sterile dressing"]

    async def aclose(self):
        pass


@pytest.mark.asyncio
async def test_fallback_is_counted_when_upstream_fails():
    mcp = FlakyMcp()
    set_mcp_client(mcp)
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            query = {"query": AMBER, "at_time": "02:00"}
            assert (await client.post("/api/triage", json=query)).status_code == 200  # saves the cache
            mcp.down = True
            assert "event: done" in (await client.post("/api/triage/stream", json=query)).text
            body = await get_metrics(client)
    finally:
        set_mcp_client(None)

    assert body["window"] == 2 and body["fallback_served"] == 1
    assert body["fallback_served_total"] == 2  # er and pharmacy both answered from the cache
    assert body["by_notice"].get("FALLBACK_CACHE") == 1
    assert body["by_source"] == {"LIVE": 1, "CACHED+LIVE": 1}
    fallback = contract(body, "RT-103", "fallback_ms")
    assert fallback["count"] == 1 and fallback["ok_rate"] == 1.0 and fallback["max_ms"] <= 200
    assert body["breakers"]["er"]["failures"] == 1 and body["breakers"]["er"]["last_error"] == "UNAVAILABLE"
