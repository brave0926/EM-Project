"""POST /api/triage/stream (SSE), offline with a fake MCP client."""

import asyncio
import json
import time
from datetime import datetime, timezone

import httpx
import pytest

from backend.app.clients.mcp_client import McpClientError, set_mcp_client
from backend.app.graph.triage_graph import stream_updates
from backend.app.main import app
from backend.app.models.domain import ERFacility, Location, PharmacyFacility
from backend.app.services.triage_stream_service import stream_triage

AMBER = "Severe burn on my hand, near Chungju Station, 2 AM"
RED = "He is unconscious"
NOW = datetime.now(timezone.utc)


class FakeMcp:
    """Per-tool delay in seconds, or "hang" (sleeps for ever) or "down" (UNAVAILABLE)."""

    def __init__(self, er=0.0, pharmacy=0.0, otc=0.0) -> None:
        self.delay = {"er": er, "pharmacy": pharmacy, "otc": otc}
        self.cancelled: list[str] = []

    async def _wait(self, tool: str) -> None:
        delay = self.delay[tool]
        if delay == "down":
            raise McpClientError("UNAVAILABLE", "cannot connect to em-mcp-server")
        try:
            await asyncio.sleep(3600 if delay == "hang" else delay)
        except asyncio.CancelledError:
            self.cancelled.append(tool)
            raise

    async def get_er_beds(self, region, near=None):
        await self._wait("er")
        return [ERFacility(name="Fake ER", location=Location(name="a", lat=36.98, lon=127.93), hvec=4,
                           tel="043-000-0000", fetched_at=NOW, distance_km=1.0)]

    async def get_pharmacies(self, near, at_time=None):
        await self._wait("pharmacy")
        return [PharmacyFacility(name="Fake Pharmacy", location=Location(name="b", lat=36.97, lon=127.9),
                                 open_until="04:00", tel="043-000-0001", fetched_at=NOW, distance_km=0.3)]

    async def get_otc(self, category):
        await self._wait("otc")
        return ["Sterile dressing"]

    async def aclose(self):
        pass


@pytest.fixture
def fake():
    def make(**delays) -> FakeMcp:
        mcp = FakeMcp(**delays)
        set_mcp_client(mcp)
        return mcp

    yield make
    set_mcp_client(None)


def parse(body: str) -> list[tuple[str, dict]]:
    events = []
    for block in body.strip().split("\n\n"):
        name, data = block.split("\n")
        assert name.startswith("event: ") and data.startswith("data: ")
        events.append((name[len("event: "):], json.loads(data[len("data: "):])))
    return events


async def post_stream(query: str, **body) -> tuple[httpx.Response, list[tuple[str, dict]]]:
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/triage/stream", json={"query": query, **body})
    return resp, parse(resp.text)


async def collect(query: str, budget_s: float = 6.0):
    """Events from the service with the arrival time (s) of each."""
    t0 = time.perf_counter()
    return [(e, time.perf_counter() - t0) async for e in stream_triage(stream_updates(query), budget_s=budget_s)]


@pytest.mark.asyncio
async def test_amber_order_and_content(fake):
    fake(er=0.05, pharmacy=0.1)
    resp, events = await post_stream(AMBER)
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    assert resp.headers["cache-control"] == "no-cache" and resp.headers["x-accel-buffering"] == "no"
    names = [name for name, _ in events]
    assert names[0] == "triage" and names[-2:] == ["advice", "done"]
    assert sorted(n for n in names if n in {"er", "pharmacy"}) == ["er", "pharmacy"]
    assert all(name == data["event"] for name, data in events)
    triage = events[0][1]
    assert (triage["severity"], triage["call_119"], triage["prompt_119"], triage["at_time"]) == ("amber", False, None, "02:00")
    assert triage["location"] == {"name": "Chungju Station (approx.)", "lat": 36.972, "lon": 127.9, "source": "text"}
    er = dict(events)["er"]["facilities"][0]
    assert (er["name"], er["status"], er["distance_km"]) == ("Fake ER", "LIVE", 1.0) and er["fetched_at"]
    pharmacy = dict(events)["pharmacy"]
    assert pharmacy["facilities"][0]["name"] == "Fake Pharmacy" and pharmacy["otc"] == ["Sterile dressing"]
    assert "Fake Pharmacy" in dict(events)["advice"]["advice"]
    done = events[-1][1]
    assert done["rt101_ok"] and done["rt105_ok"] and not done["timed_out"]
    assert set(done["stages"]) == {"triage", "er", "pharmacy", "advice"}
    assert done["stages"]["triage"] <= done["stages"]["er"] <= done["stages"]["advice"] <= done["total_ms"]


@pytest.mark.asyncio
async def test_red_starts_with_119_and_skips_pharmacy(fake):
    mcp = fake(er=0.05)
    _, events = await post_stream(RED)
    names = [name for name, _ in events]
    first = events[0][1]
    assert names[0] == "triage" and first["severity"] == "red" and first["call_119"] is True
    assert first["prompt_119"] == "This may be life-threatening. Call 119 now." and first["at_time"] is None
    assert "pharmacy" not in names and names[-2:] == ["advice", "done"]
    assert ("notice", "LOCATION_DEFAULT") in [(n, d.get("notice")) for n, d in events]
    assert events[-2][1]["advice"].startswith("This may be life-threatening")
    assert mcp.cancelled == []


@pytest.mark.asyncio
async def test_first_event_long_before_a_slow_upstream(fake):
    fake(er=1.8, pharmacy=1.8, otc=1.8)
    events = await collect(AMBER)
    (first, t_first), (done, t_done) = events[0], events[-1]
    assert first.event == "triage" and t_first < 0.2  # << 1.8 s upstream; RT-101 is 1.5 s
    assert t_done >= 1.8 and done.rt101_ok and done.rt105_ok


@pytest.mark.asyncio
async def test_hanging_worker_still_ends_with_done(fake):
    mcp = fake(er="hang", pharmacy=0.01)
    t0 = time.perf_counter()
    events = [e for e, _ in await collect(AMBER, budget_s=0.3)]
    assert time.perf_counter() - t0 < 1.0  # never hangs
    names = [e.event for e in events]
    assert names[0] == "triage" and "pharmacy" in names and "er" not in names
    assert names[-2:] == ["advice", "done"]
    assert any(e.event == "notice" and e.notice == "ER_UNAVAILABLE" for e in events)
    done = events[-1]
    assert done.timed_out and not done.rt105_ok and done.rt101_ok
    assert "Fake Pharmacy" in events[-2].advice and "119" in events[-2].advice
    await asyncio.sleep(0)
    assert mcp.cancelled == ["er"]  # the hung worker was cancelled at the cap


@pytest.mark.asyncio
async def test_failing_worker_emits_notice_and_stream_continues(fake):
    fake(er="down")
    _, events = await post_stream(AMBER)
    notices = [d["notice"] for n, d in events if n == "notice"]
    assert {"ER_UNAVAILABLE", "NO_DATA"} <= set(notices)
    assert dict(events)["er"]["facilities"] == [] and events[-1][0] == "done"
    assert events[-1][1]["rt105_ok"] is True


@pytest.mark.asyncio
async def test_client_disconnect_cancels_workers(fake):
    mcp = fake(er="hang", pharmacy="hang", otc="hang")
    events = stream_triage(stream_updates(AMBER))
    first = await anext(events)
    assert first.event == "triage"
    pending = asyncio.ensure_future(anext(events))  # waiting for the workers
    await asyncio.sleep(0.05)
    pending.cancel()  # what Starlette does when the client goes away
    with pytest.raises(asyncio.CancelledError):
        await pending
    await events.aclose()
    assert sorted(mcp.cancelled) == ["er", "otc", "pharmacy"]


def test_swagger_documents_the_stream():
    spec = app.openapi()
    op = spec["paths"]["/api/triage/stream"]["post"]
    content = op["responses"]["200"]["content"]["text/event-stream"]
    assert "event: triage" in content["example"] and "rt105_ok" in op["responses"]["200"]["description"]
    assert op["tags"] == ["Triage"]
