import time

import pytest

from backend.app.models.domain import Location
from backend.app.models.enums import Category, DataStatus
from mcp_server.providers import (
    LiveProvider,
    MockProvider,
    ProviderError,
    get_provider,
)

TOLERANCE_MS = 100  # event-loop scheduling slack
CHUNGJU = Location(name="Chungju City Hall (mock)", lat=36.991, lon=127.926)


def _fast(**kwargs) -> MockProvider:
    return MockProvider(delay_ms_range=(0, 0), seed=1, **kwargs)


@pytest.mark.asyncio
async def test_delay_within_range():
    provider = MockProvider(delay_ms_range=(50, 120), seed=42)
    for _ in range(3):
        t0 = time.perf_counter()
        await provider.get_er_beds("Chungju")
        elapsed_ms = (time.perf_counter() - t0) * 1000
        assert 50 <= elapsed_ms <= 120 + TOLERANCE_MS


@pytest.mark.asyncio
async def test_failure_rate_one_raises():
    provider = _fast(failure_rate=1.0)
    with pytest.raises(ProviderError):
        await provider.get_er_beds("Chungju")
    with pytest.raises(ProviderError):
        await provider.get_pharmacies(CHUNGJU)


@pytest.mark.asyncio
async def test_fresh_data_is_live_and_mock():
    ers = await _fast().get_er_beds("Chungju", near=CHUNGJU)
    assert len(ers) == 3
    assert all(e.status is DataStatus.LIVE and e.source == "MOCK" for e in ers)
    assert any(e.hvec == 0 for e in ers)
    assert [e.distance_km for e in ers] == sorted(e.distance_km for e in ers)


@pytest.mark.asyncio
async def test_stale_minutes_200_gives_uncertain():
    provider = _fast(stale_minutes=200)
    ers = await provider.get_er_beds("Chungju")
    pharmacies = await provider.get_pharmacies(CHUNGJU, at_time="12:00")
    assert ers and all(e.status is DataStatus.UNCERTAIN for e in ers)
    assert pharmacies and all(p.status is DataStatus.UNCERTAIN for p in pharmacies)


@pytest.mark.asyncio
async def test_closed_pharmacy_filtered_at_0500():
    names = {p.name for p in await _fast().get_pharmacies(CHUNGJU, at_time="05:00")}
    assert "Yeonsu Central Pharmacy (mock)" in names  # open until 06:00
    assert "Station Night Pharmacy (mock)" not in names  # closed at 04:00
    assert "Campus Pharmacy (mock)" not in names  # closed at 23:00


@pytest.mark.asyncio
async def test_otc_generic_only():
    provider = _fast()
    assert "Sterile dressing" in await provider.get_otc(Category.CUT)
    assert await provider.get_otc(Category.CRITICAL) == []


def test_factory_default_is_mock(monkeypatch):
    monkeypatch.delenv("EM_PROVIDER", raising=False)
    assert isinstance(get_provider(), MockProvider)
    monkeypatch.setenv("EM_PROVIDER", "live")
    assert isinstance(get_provider(), LiveProvider)
    monkeypatch.setenv("EM_PROVIDER", "bogus")
    with pytest.raises(ValueError):
        get_provider()


@pytest.mark.asyncio
async def test_live_provider_without_key_raises_provider_error():
    live = LiveProvider(er_key="", pharmacy_key="")
    with pytest.raises(ProviderError, match="NO_KEY"):
        await live.get_er_beds("Chungju")
    with pytest.raises(ProviderError, match="NO_KEY"):
        await live.get_pharmacies(CHUNGJU)
    assert await live.get_otc(Category.CUT)  # static lists, no upstream call
