import time

import pytest

from backend.app.graph.triage_graph import run_triage
from backend.app.models.enums import Category, Language, Notice, Severity
from mcp_server.providers import MockProvider
from mcp_server.server import build_server

DEMO = "Severe burn on my hand, near Chungju Station, 2 AM"


class CountingProvider(MockProvider):
    def __init__(self, **kwargs):
        super().__init__(**({"delay_ms_range": (0, 0), "seed": 1} | kwargs))
        self.calls: list[str] = []

    async def get_er_beds(self, *a, **k):
        self.calls.append("er")
        return await super().get_er_beds(*a, **k)

    async def get_pharmacies(self, *a, **k):
        self.calls.append("pharmacy")
        return await super().get_pharmacies(*a, **k)

    async def get_otc(self, *a, **k):
        self.calls.append("otc")
        return await super().get_otc(*a, **k)


@pytest.mark.asyncio
async def test_demo_query_end_to_end(use_mcp):
    use_mcp()
    out = await run_triage(DEMO)
    assert (out.language, out.category, out.severity, out.call_119) == (
        Language.EN, Category.BURN, Severity.AMBER, False)
    assert (out.location.name, out.location_source, out.at_time) == ("Chungju Station (approx.)", "text", "02:00")
    assert out.pharmacies[0].name == "Station Night Pharmacy (mock)"  # open at 02:00, 0.3 km away
    assert out.er[0].hvec > 0 and out.er[-1].hvec == 0  # free beds first
    assert "Sterile non-adherent dressing" in out.otc
    assert out.notices == []
    assert "Station Night Pharmacy (mock)" in out.advice and "119" in out.advice.splitlines()[-1]


@pytest.mark.asyncio
async def test_workers_run_in_parallel(use_mcp):
    use_mcp(delay_ms_range=(300, 300))
    t0 = time.perf_counter()
    out = await run_triage(DEMO)
    elapsed = time.perf_counter() - t0
    assert out.er and out.pharmacies and out.otc
    assert elapsed < 0.55  # er, pharmacy and otc in parallel; sequential would be >= 0.9 s


@pytest.mark.asyncio
async def test_critical_korean_calls_119_and_skips_pharmacy(use_mcp):
    provider = CountingProvider()
    use_mcp(server=build_server(provider))
    out = await run_triage("아버지가 의식이 없어요, 충주역")
    assert (out.language, out.severity, out.call_119) == (Language.KO, Severity.RED, True)
    assert provider.calls == ["er"]
    assert out.er and out.pharmacies == [] and out.otc == [] and out.at_time is None
    assert out.advice.startswith("생명이 위험할 수 있습니다. 지금 바로 119에 전화하세요.")


@pytest.mark.asyncio
@pytest.mark.parametrize("query", [DEMO, "He is unconscious"])
async def test_mcp_down_still_answers(use_mcp, query):
    use_mcp(server="http://127.0.0.1:9/mcp")
    out = await run_triage(query)
    assert out.er == [] and out.pharmacies == []
    assert Notice.ER_UNAVAILABLE in out.notices
    assert "119" in out.advice
    if out.severity is Severity.RED:
        assert out.call_119 and Notice.PHARMACY_UNAVAILABLE not in out.notices
    else:
        assert {Notice.PHARMACY_UNAVAILABLE, Notice.OTC_UNAVAILABLE} <= set(out.notices)


@pytest.mark.asyncio
async def test_provider_failure_becomes_notices(use_mcp):
    use_mcp(failure_rate=1.0)
    out = await run_triage(DEMO)
    assert {Notice.ER_UNAVAILABLE, Notice.PHARMACY_UNAVAILABLE, Notice.OTC_UNAVAILABLE} <= set(out.notices)
    assert out.severity is Severity.AMBER


@pytest.mark.asyncio
async def test_stale_data_and_default_location_notices(use_mcp):
    use_mcp(stale_minutes=200)
    out = await run_triage("small cut on my finger at 12:00")
    assert out.location_source == "default"
    assert out.notices == [Notice.LOCATION_DEFAULT, Notice.DATA_UNCERTAIN]


@pytest.mark.asyncio
async def test_no_open_pharmacy_notice(use_mcp):
    use_mcp()
    out = await run_triage("small cut near Chungju Station at 07:00")  # mock: none open 06:00-09:00
    assert out.pharmacies == [] and Notice.NO_OPEN_PHARMACY in out.notices
    out = await run_triage("small cut near Chungju Station at 05:30")  # only Yeonsu Central is open
    assert [p.name for p in out.pharmacies] == ["Yeonsu Central Pharmacy (mock)"]


@pytest.mark.asyncio
async def test_request_fields_override_text(use_mcp):
    use_mcp()
    out = await run_triage("ожог руки", language=Language.EN, lat=36.989, lon=127.927, at_time="12:00")
    assert (out.language, out.category, out.location_source, out.at_time) == (
        Language.EN, Category.BURN, "request", "12:00")
    assert out.advice.startswith("This can usually be handled with first aid.")


@pytest.mark.asyncio
async def test_rt105_end_to_end_with_default_mock_latency(use_mcp):
    use_mcp(delay_ms_range=(500, 1100), seed=7)
    out = await run_triage(DEMO)
    assert out.total_ms <= 6000  # RT-105
