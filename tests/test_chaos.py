"""/demo/chaos failure injection (offline: fake MCP client, fake clocks)."""

import asyncio
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from backend.app.clients import mcp_client
from backend.app.clients.chaos import ChaosStore, get_chaos_store, set_chaos_store
from backend.app.clients.mcp_client import ChaosMcpClient, McpClientError, get_mcp_client, set_mcp_client
from backend.app.main import app
from backend.app.models.chaos import ChaosMode, ChaosRule, ChaosTarget
from backend.app.models.domain import ERFacility, Location, PharmacyFacility
from backend.app.models.enums import DataStatus, Notice
from backend.app.services import chaos_service, er_facility_service, fallback_service
from backend.app.services.circuit_breaker import BreakerState

AMBER = {"query": "Severe burn on my hand, near Chungju Station, 2 AM"}
FETCHED = datetime.now(timezone.utc) - timedelta(minutes=5)
LAT, LON = 36.99, 127.93


class FakeMcp:
    """A healthy upstream that counts calls per tool."""

    def __init__(self, timeout_s: float = 2.0) -> None:
        self.timeout_s = timeout_s
        self.calls = {"er": 0, "pharmacy": 0, "otc": 0}

    async def get_er_beds(self, region, near=None):
        self.calls["er"] += 1
        await asyncio.sleep(0)
        return [ERFacility(name="ER", location=Location(name="a", lat=36.98, lon=127.93), hvec=2,
                           tel="043-000-0000", fetched_at=FETCHED, source="LIVE", distance_km=1.0)]

    async def get_pharmacies(self, near, at_time=None):
        self.calls["pharmacy"] += 1
        return [PharmacyFacility(name="Ph", location=Location(name="b", lat=36.97, lon=127.9), open_until="04:00",
                                 tel="043-000-0001", fetched_at=FETCHED, source="LIVE", distance_km=0.3)]

    async def get_otc(self, category):
        self.calls["otc"] += 1
        return ["Sterile dressing"]

    async def aclose(self):
        pass


@pytest.fixture
def fake(monkeypatch):
    monkeypatch.setenv("EM_DEMO_CHAOS", "1")
    mcp = FakeMcp()
    set_mcp_client(mcp)
    yield mcp
    set_mcp_client(None)


@pytest.fixture
def clock():
    """Fake clock shared by the breakers and the chaos store."""
    now = [1000.0]
    fallback_service.reset_breakers(clock=lambda: now[0])
    set_chaos_store(ChaosStore(clock=lambda: now[0]))
    return now


def client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def triage(c: httpx.AsyncClient) -> dict:
    response = await c.post("/api/triage", json=AMBER)
    assert response.status_code == 200
    return response.json()


@pytest.mark.asyncio
async def test_endpoints_are_404_when_disabled():
    async with client() as c:
        assert (await c.get("/demo/chaos")).status_code == 404
        assert (await c.post("/demo/chaos", json={"target": "all", "mode": "error"})).status_code == 404
        assert (await c.delete("/demo/chaos")).status_code == 404
        assert "/demo/chaos" not in (await c.get("/openapi.json")).json()["paths"]  # off at start: not listed


def test_rules_are_ignored_when_disabled():
    store = get_chaos_store()
    store.set("er", ChaosRule(mode=ChaosMode.ERROR, expires_at=store.clock() + 60))
    assert not isinstance(get_mcp_client(), ChaosMcpClient)  # EM_DEMO_CHAOS unset


@pytest.mark.asyncio
async def test_chaos_off_is_the_plain_client_and_same_answer(fake):
    assert get_mcp_client() is fake  # enabled, but no rule: not even wrapped
    async with client() as c:
        before = await triage(c)
        await c.post("/demo/chaos", json={"target": "all", "mode": "error"})
        await c.post("/demo/chaos", json={"target": "all", "mode": "off"})
        assert get_mcp_client() is fake
        after = await triage(c)
    drop = {"total_ms"}
    assert {k: v for k, v in before.items() if k not in drop} == {k: v for k, v in after.items() if k not in drop}
    assert after["notices"] == [] and all(e["status"] == "LIVE" for e in after["er"])


@pytest.mark.asyncio
async def test_error_mode_opens_circuit_and_serves_cache(fake, clock, fresh_fallback):
    async with client() as c:
        warm = await triage(c)  # fills the cache
        saved = await fresh_fallback.load("er", "chungju")
        state = (await c.post("/demo/chaos", json={"target": "all", "mode": "error", "duration_s": 120})).json()
        assert state["active"] and state["tools"]["er"] == {"mode": "error", "delay_ms": None, "seconds_left": 120}

        for i in range(3):
            body = await triage(c)
            assert Notice.FALLBACK_CACHE in body["notices"]
            assert [e["status"] for e in body["er"]] == ["CACHED"] and body["er"][0]["fetched_at"] == warm["er"][0]["fetched_at"]
        health = (await c.get("/health")).json()["breakers"]
        assert health["er"] == {"state": "OPEN", "failures": 3, "last_error": "TOOL_ERROR"}
        assert health["pharmacy"]["state"] == "OPEN"

        await triage(c)  # circuit open: upstream skipped, still answered from the cache
        metrics = (await c.get("/metrics", params={"recent": 5})).json()

    assert fake.calls["er"] == 1 and fake.calls["pharmacy"] == 1  # only the warm-up reached upstream
    assert await fresh_fallback.load("er", "chungju") == saved  # chaos wrote nothing to the cache
    assert [r["er_ms"] is None for r in metrics["recent"]] == [False, False, False, False, True]
    assert all(r["fallback_ms"] is not None for r in metrics["recent"][1:])
    rt103 = next(x for x in metrics["contracts"] if x["contract"] == "RT-103")
    assert rt103["count"] == 4 and rt103["ok_rate"] == 1.0
    assert metrics["by_chaos"] == {"on": 4, "off": 1}
    assert [r["chaos_active"] for r in metrics["recent"]] == [False, True, True, True, True]


@pytest.mark.asyncio
async def test_hang_mode_costs_the_rt102_timeout(fake):
    fake.timeout_s = 0.2  # the wrapper uses the client's own RT-102 timeout
    await er_facility_service.find_ers("Chungju", LAT, LON)  # cache
    chaos_service.set_chaos(ChaosTarget.ER, ChaosMode.HANG)
    loop = asyncio.get_running_loop()
    t0 = loop.time()
    ers, notices = await er_facility_service.find_ers("Chungju", LAT, LON)
    assert loop.time() - t0 >= 0.2
    assert notices == [Notice.FALLBACK_CACHE] and ers[0].status is DataStatus.CACHED
    assert fallback_service.breaker_status()["er"]["last_error"] == "TIMEOUT"
    assert fake.calls["er"] == 1  # the hang never reached upstream


@pytest.mark.asyncio
async def test_delay_mode_passes_or_times_out(fake):
    fake.timeout_s = 0.3
    chaos_service.set_chaos(ChaosTarget.ER, ChaosMode.DELAY, delay_ms=50)
    wrapped = get_mcp_client()
    loop = asyncio.get_running_loop()
    t0 = loop.time()
    assert (await wrapped.get_er_beds("Chungju"))[0].name == "ER" and loop.time() - t0 >= 0.05
    chaos_service.set_chaos(ChaosTarget.ER, ChaosMode.DELAY, delay_ms=1000)
    with pytest.raises(McpClientError) as err:
        await get_mcp_client().get_er_beds("Chungju")
    assert err.value.code == "TIMEOUT"
    assert await get_mcp_client().get_otc("burn") == ["Sterile dressing"]  # OTC is never targeted
    assert await get_mcp_client().get_pharmacies(Location(name="u", lat=LAT, lon=LON))  # only er targeted


def test_auto_expiry_and_limits(fake, clock):
    chaos_service.set_chaos(ChaosTarget.ALL, ChaosMode.ERROR, duration_s=60)
    clock[0] += 59
    assert chaos_service.get_state().tools["er"].seconds_left == 1 and isinstance(get_mcp_client(), ChaosMcpClient)
    clock[0] += 1
    state = chaos_service.get_state()
    assert not state.active and state.tools["er"].mode is ChaosMode.OFF and get_mcp_client() is fake
    assert chaos_service.set_chaos(ChaosTarget.ER, ChaosMode.HANG, duration_s=10_000).tools["er"].seconds_left == 300
    assert chaos_service.set_chaos(ChaosTarget.ER, ChaosMode.DELAY).tools["er"].delay_ms == 3000


@pytest.mark.asyncio
async def test_request_limits_are_validated(fake):
    async with client() as c:
        assert (await c.post("/demo/chaos", json={"target": "all", "mode": "error", "duration_s": 301})).status_code == 422
        assert (await c.post("/demo/chaos", json={"target": "otc", "mode": "error"})).status_code == 422


@pytest.mark.asyncio
async def test_delete_then_half_open_recovery_closes_the_breaker(fake, clock):
    async with client() as c:
        await triage(c)
        await c.post("/demo/chaos", json={"target": "all", "mode": "error"})
        for _ in range(3):
            await triage(c)
        state = (await c.delete("/demo/chaos")).json()
        assert not state["active"] and state["tools"]["er"]["mode"] == "off"

        body = await triage(c)  # still OPEN: cached, upstream skipped
        assert Notice.FALLBACK_CACHE in body["notices"] and fake.calls["er"] == 1

        clock[0] += 30  # HALF_OPEN: one trial goes upstream and succeeds
        assert (await c.get("/health")).json()["breakers"]["er"]["state"] == "HALF_OPEN"
        body = await triage(c)
        breakers = (await c.get("/health")).json()["breakers"]
    assert body["notices"] == [] and body["er"][0]["status"] == "LIVE" and fake.calls["er"] == 2
    assert breakers["er"]["state"] == breakers["pharmacy"]["state"] == BreakerState.CLOSED
    assert mcp_client.get_mcp_client() is fake
