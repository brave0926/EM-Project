"""Circuit breaker and SQLite fallback cache (offline: fake MCP client, fake clock)."""

import asyncio
import time
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from backend.app.clients.fallback_store import FallbackStore, set_fallback_store
from backend.app.clients.mcp_client import McpClientError, set_mcp_client
from backend.app.main import app
from backend.app.models.domain import ERFacility, Location, PharmacyFacility
from backend.app.models.enums import DataStatus, Notice
from backend.app.services import er_facility_service, fallback_service, pharmacy_facility_service
from backend.app.services.circuit_breaker import BreakerState, CircuitBreaker

RT_103_S = 0.2
TIMEOUT_S = 2.0  # RT-102: what a hung em-mcp-server costs before the client gives up
LAT, LON = 36.99, 127.93
FAKE_KEY = "fake+key/for==tests"
FETCHED = datetime.now(timezone.utc) - timedelta(minutes=5)


def er(name: str, lat: float, hvec: int, fetched_at: datetime = FETCHED) -> ERFacility:
    return ERFacility(name=name, location=Location(name="addr", lat=lat, lon=127.93), hvec=hvec,
                      tel="043-000-0000", fetched_at=fetched_at, source="LIVE", distance_km=1.0)


def pharmacy(name: str, lat: float) -> PharmacyFacility:
    return PharmacyFacility(name=name, location=Location(name="addr", lat=lat, lon=127.93), open_until="22:00",
                            tel="043-000-0001", fetched_at=FETCHED, source="LIVE", distance_km=1.0)


class FakeMcp:
    """Stands in for McpClient. mode: ok | hang (TIMEOUT after timeout_s) | down (UNAVAILABLE)."""

    def __init__(self, timeout_s: float = TIMEOUT_S) -> None:
        self.mode = "ok"
        self.timeout_s = timeout_s
        self.calls = 0
        self.ers = [er("Near ER", 36.98, 3), er("Far ER", 36.90, 1)]
        self.pharmacies = [pharmacy("Near Pharmacy", 36.991), pharmacy("Far Pharmacy", 36.95)]

    async def _answer(self, value):
        self.calls += 1
        if self.mode == "hang":
            await asyncio.sleep(self.timeout_s)
            raise McpClientError("TIMEOUT", f"no answer within {self.timeout_s:.2f} s")
        if self.mode == "down":
            raise McpClientError("UNAVAILABLE", "cannot connect to em-mcp-server")
        return value

    async def get_er_beds(self, region, near=None):
        return await self._answer(list(self.ers))

    async def get_pharmacies(self, near, at_time=None):
        return await self._answer(list(self.pharmacies))

    async def get_otc(self, category):
        return await self._answer(["Sterile dressing"])

    async def aclose(self):
        pass


@pytest.fixture
def clock():
    now = [1000.0]
    fallback_service.reset_breakers(clock=lambda: now[0])
    return now


@pytest.fixture
def mcp():
    fake = FakeMcp()
    set_mcp_client(fake)
    yield fake
    set_mcp_client(None)


def api() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


# --- breaker state machine -------------------------------------------------------------


def test_breaker_opens_after_three_failures_and_recovers():
    now = [0.0]
    b = CircuitBreaker(clock=lambda: now[0])
    for _ in range(2):
        assert b.allow()
        b.record_failure("TIMEOUT")
    assert b.state is BreakerState.CLOSED and b.failures == 2
    assert b.allow()
    b.record_failure("UNAVAILABLE")
    assert b.state is BreakerState.OPEN and b.last_error == "UNAVAILABLE"
    now[0] = 29.9
    assert not b.allow() and b.state is BreakerState.OPEN  # stays open 30 s
    now[0] = 30.0
    assert b.state is BreakerState.HALF_OPEN
    assert b.allow()  # one trial call
    assert not b.allow()  # a second caller during the trial is refused
    b.record_success()
    assert b.state is BreakerState.CLOSED and b.failures == 0 and b.allow()


def test_half_open_trial_failure_reopens():
    now = [0.0]
    b = CircuitBreaker(clock=lambda: now[0])
    for _ in range(3):
        b.record_failure("TOOL_ERROR")
    now[0] = 30.0
    assert b.allow()
    b.record_failure("BAD_RESPONSE")
    assert b.state is BreakerState.OPEN
    now[0] = 59.9
    assert not b.allow()
    now[0] = 60.0
    assert b.allow()


def test_success_resets_consecutive_count_and_release_frees_trial():
    now = [0.0]
    b = CircuitBreaker(clock=lambda: now[0])
    b.record_failure("TIMEOUT"), b.record_failure("TIMEOUT"), b.record_success()
    b.record_failure("TIMEOUT"), b.record_failure("TIMEOUT")
    assert b.state is BreakerState.CLOSED
    b.record_failure("TIMEOUT")
    now[0] = 30.0
    assert b.allow()
    b.release()  # e.g. the trial call was cancelled
    assert b.allow()


# --- fallback --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_hang_served_from_cache_within_rt103(mcp, clock):
    live, notices = await er_facility_service.find_ers("Chungju", LAT, LON)
    assert notices == [] and all(e.status is DataStatus.LIVE for e in live)
    mcp.mode = "hang"
    t0 = time.perf_counter()
    cached, notices = await er_facility_service.find_ers("Chungju", LAT, LON)
    fallback_s = time.perf_counter() - t0 - TIMEOUT_S
    assert fallback_s <= RT_103_S
    assert notices == [Notice.FALLBACK_CACHE]
    assert [e.name for e in cached] == ["Near ER", "Far ER"]
    assert all(e.status is DataStatus.CACHED for e in cached)
    assert [e.fetched_at for e in cached] == [e.fetched_at for e in live]  # age stays visible


@pytest.mark.asyncio
async def test_open_circuit_skips_upstream_and_answers_fast(mcp, clock):
    await er_facility_service.find_ers("Chungju", LAT, LON)
    mcp.mode, mcp.timeout_s = "hang", 0.01
    for _ in range(3):
        _, notices = await er_facility_service.find_ers("Chungju", LAT, LON)
        assert notices == [Notice.FALLBACK_CACHE]
    status = fallback_service.breaker_status()["er"]
    assert status == {"state": BreakerState.OPEN, "failures": 3, "last_error": "TIMEOUT"}
    calls = mcp.calls
    t0 = time.perf_counter()
    ers, notices = await er_facility_service.find_ers("Chungju", LAT, LON)
    assert time.perf_counter() - t0 <= RT_103_S
    assert mcp.calls == calls and ers and notices == [Notice.FALLBACK_CACHE]  # no upstream call
    assert fallback_service.breaker_status()["pharmacy"]["state"] == BreakerState.CLOSED  # per tool

    clock[0] += 30  # HALF_OPEN: one trial goes upstream
    mcp.mode = "ok"
    _, notices = await er_facility_service.find_ers("Chungju", LAT, LON)
    assert mcp.calls == calls + 1 and notices == []
    assert fallback_service.breaker_status()["er"]["state"] == BreakerState.CLOSED


@pytest.mark.asyncio
async def test_old_cache_is_uncertain(mcp, clock):
    mcp.ers = [er("Old ER", 36.98, 2, fetched_at=datetime.now(timezone.utc) - timedelta(minutes=200))]
    await er_facility_service.find_ers("Chungju", LAT, LON)
    mcp.mode = "down"
    ers, notices = await er_facility_service.find_ers("Chungju", LAT, LON)
    assert notices == [Notice.FALLBACK_CACHE] and ers[0].status is DataStatus.UNCERTAIN


@pytest.mark.asyncio
async def test_cached_distances_are_recomputed(mcp, clock):
    await er_facility_service.find_ers("Chungju", LAT, LON)
    mcp.mode = "down"
    ers, _ = await er_facility_service.find_ers("Chungju", 36.90, 127.93)  # standing next to Far ER
    assert ers[0].name == "Far ER" and ers[0].distance_km == pytest.approx(0.0, abs=0.01)


@pytest.mark.asyncio
async def test_pharmacy_cache_for_another_time_has_unknown_open_status(mcp, clock):
    await pharmacy_facility_service.find_open_pharmacies(LAT, LON, "12:00")
    mcp.mode = "down"
    _, same, notices = await pharmacy_facility_service.find_open_pharmacies(LAT, LON, "12:00")
    assert notices == [Notice.FALLBACK_CACHE] and all(p.is_open is True for p in same)
    _, other, _ = await pharmacy_facility_service.find_open_pharmacies(LAT, LON, "23:00")
    assert [p.name for p in other] == ["Near Pharmacy", "Far Pharmacy"]
    assert all(p.is_open is None for p in other)


@pytest.mark.asyncio
async def test_slow_store_counts_as_no_cache(mcp, clock, fresh_fallback, monkeypatch):
    await er_facility_service.find_ers("Chungju", LAT, LON)

    async def slow_load(tool, key):
        await asyncio.sleep(1)

    monkeypatch.setattr(fresh_fallback, "load", slow_load)
    mcp.mode = "down"
    t0 = time.perf_counter()
    with pytest.raises(McpClientError, match="UNAVAILABLE"):
        await er_facility_service.find_ers("Chungju", LAT, LON)
    assert time.perf_counter() - t0 <= RT_103_S + 0.05


# --- endpoints -------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(("mode", "status"), [("down", 503), ("hang", 504)])
async def test_endpoint_without_cache_keeps_error_mapping(mcp, clock, mode, status):
    mcp.mode, mcp.timeout_s = mode, 0.01
    async with api() as client:
        resp = await client.get("/facilities/er", params={"lat": LAT, "lon": LON})
    assert resp.status_code == status


@pytest.mark.asyncio
async def test_endpoints_use_cache_first(mcp, clock):
    async with api() as client:
        await client.get("/facilities/er", params={"lat": LAT, "lon": LON})
        await client.get("/facilities/ph", params={"lat": LAT, "lon": LON, "at_time": "12:00"})
        mcp.mode = "down"
        er_body = (await client.get("/facilities/er", params={"lat": LAT, "lon": LON})).json()
        ph_body = (await client.get("/facilities/ph", params={"lat": LAT, "lon": LON, "at_time": "12:00"})).json()
        health = (await client.get("/health")).json()
    assert er_body["notices"] == ["FALLBACK_CACHE"] and er_body["count"] == 2
    assert {f["status"] for f in er_body["facilities"]} == {"CACHED"}
    assert ph_body["notices"] == ["FALLBACK_CACHE"] and ph_body["count"] == 2
    assert health["breakers"]["er"] == {"state": "CLOSED", "failures": 1, "last_error": "UNAVAILABLE"}


@pytest.mark.asyncio
async def test_triage_without_cache_is_200_with_no_data(mcp, clock):
    mcp.mode = "down"
    async with api() as client:
        resp = await client.post("/api/triage", json={"query": "Bad cut on my arm", "at_time": "12:00"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["severity"] and body["er"] == [] and body["pharmacies"] == []
    assert {"ER_UNAVAILABLE", "PHARMACY_UNAVAILABLE", "NO_DATA"} <= set(body["notices"])
    assert "119" in body["advice"]


@pytest.mark.asyncio
async def test_triage_with_cache_shows_saved_er(mcp, clock):
    async with api() as client:
        await client.post("/api/triage", json={"query": "He is unconscious"})
        mcp.mode = "down"
        body = (await client.post("/api/triage", json={"query": "He is unconscious"})).json()
    assert body["call_119"] is True and body["er"][0]["name"] == "Near ER"
    assert "FALLBACK_CACHE" in body["notices"] and "NO_DATA" not in body["notices"]


# --- persistence -----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cache_survives_restart_and_holds_no_key_or_url(mcp, clock, tmp_path):
    path = tmp_path / "restart.db"
    set_fallback_store(FallbackStore(path))
    await er_facility_service.find_ers("Chungju", LAT, LON)
    await pharmacy_facility_service.find_open_pharmacies(LAT, LON, "12:00")

    set_fallback_store(FallbackStore(path))  # new process: new store object, new breakers
    fallback_service.reset_breakers(clock=lambda: clock[0])
    mcp.mode = "down"
    ers, notices = await er_facility_service.find_ers("Chungju", LAT, LON)
    assert notices == [Notice.FALLBACK_CACHE] and ers[0].name == "Near ER"

    raw = path.read_bytes()
    for secret in (b"http", b"serviceKey", FAKE_KEY.encode()):
        assert secret not in raw
