"""LiveProvider against the saved data.go.kr samples (docs/samples), fully offline."""

import asyncio
import xml.etree.ElementTree as ET
from datetime import datetime, time
from pathlib import Path

import httpx
import pytest

from backend.app.models.domain import Location
from backend.app.models.enums import Category, DataStatus
from mcp_server import providers
from mcp_server.providers import (
    KST,
    LiveProvider,
    MockProvider,
    ProviderError,
    get_provider,
    open_status,
    parse_hvidate,
    parse_nmc_hhmm,
    region_stages,
)

SAMPLES = Path(__file__).resolve().parent.parent / "docs" / "samples"
FAKE_KEY = "fake+key/for==tests"  # not a real key
PATIENT = Location(name="patient", lat=36.99, lon=127.93)


def sample(name: str) -> str:
    return (SAMPLES / name).read_text(encoding="utf-8")


def edit(xml: str, hpid: str, **tags: str | None) -> str:
    """Set (or with None, remove) tags on the item with this hpid."""
    root = ET.fromstring(xml)
    for item in root.iter("item"):
        if item.findtext("hpid") != hpid:
            continue
        for tag, value in tags.items():
            node = item.find(tag)
            if value is None:
                if node is not None:
                    item.remove(node)
            else:
                if node is None:
                    node = ET.SubElement(item, tag)
                node.text = value
    return ET.tostring(root, encoding="unicode")


class Upstream:
    """httpx.MockTransport that serves the samples per operation and counts calls."""

    def __init__(self, **overrides: str) -> None:
        self.responses = {
            "getEmrrmRltmUsefulSckbdInfoInqire": sample("er_beds.xml"),
            "getParmacyLcinfoInqire": sample("pharmacies_radius.xml"),
            **overrides,
        }
        self.calls: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        op = request.url.path.rsplit("/", 1)[-1]
        if op == "getEgytBassInfoInqire":
            hpid = request.url.params["HPID"]
            body = self.responses.get(f"basic:{hpid}") or sample(f"er_basic_{hpid}.xml")
        else:
            body = self.responses[op]
        return httpx.Response(200, text=body)

    def count(self, op: str) -> int:
        return sum(r.url.path.endswith(op) for r in self.calls)


def live(upstream: Upstream, **kwargs) -> LiveProvider:
    return LiveProvider(
        er_key=FAKE_KEY, pharmacy_key="", transport=httpx.MockTransport(upstream.handler), **kwargs
    )


@pytest.mark.asyncio
async def test_er_beds_parse_join_and_sort():
    up = Upstream()
    ers = await live(up).get_er_beds("Chungju", near=PATIENT)
    assert [e.name for e in ers] == ["건국대학교충주병원", "충청북도충주의료원"]  # nearest first
    konkuk = ers[0]
    assert (konkuk.hvec, konkuk.hvicc, konkuk.tel) == (19, 2, "043-840-8593")
    assert konkuk.location.lat == pytest.approx(36.97897509717851)
    assert konkuk.location.name == "충청북도 충주시 국원대로 82 (교현동)"
    assert all(e.source == "LIVE" for e in ers)
    assert [e.distance_km for e in ers] == sorted(e.distance_km for e in ers)
    params = up.calls[0].url.params
    assert (params["STAGE1"], params["STAGE2"], params["numOfRows"]) == ("충청북도", "충주시", "30")
    assert params["serviceKey"] == FAKE_KEY  # plain query param, encoded once by httpx
    assert up.count("getEgytBassInfoInqire") == 2


@pytest.mark.asyncio
async def test_hvidate_becomes_kst_fetched_at():
    ers = await live(Upstream()).get_er_beds("Chungju")
    assert ers[0].fetched_at == datetime(2026, 10, 27, 11, 5, 1, tzinfo=KST)
    assert parse_hvidate("20261027110501").utcoffset().total_seconds() == 9 * 3600
    assert parse_hvidate("2026-10-27") is None and parse_hvidate(None) is None


@pytest.mark.asyncio
async def test_negative_hvec_is_zero():
    beds = edit(sample("er_beds.xml"), "A2300004", hvec="-3")
    ers = await live(Upstream(getEmrrmRltmUsefulSckbdInfoInqire=beds)).get_er_beds("Chungju")
    assert {e.name: e.hvec for e in ers}["충청북도충주의료원"] == 0


@pytest.mark.asyncio
async def test_hospital_without_bed_data_is_dropped():
    beds = edit(sample("er_beds.xml"), "A2300004", hvec=None)
    up = Upstream(getEmrrmRltmUsefulSckbdInfoInqire=beds)
    ers = await live(up).get_er_beds("Chungju")
    assert [e.name for e in ers] == ["건국대학교충주병원"]
    assert up.count("getEgytBassInfoInqire") == 1  # no lookup for a dropped hospital


@pytest.mark.asyncio
async def test_missing_tags_are_unknown_not_zero():
    beds = edit(sample("er_beds.xml"), "A2300010", hvicc=None, hvidate=None, dutyTel3=None)
    basic = edit(sample("er_basic_A2300004.xml"), "A2300004", wgs84Lat=None)
    up = Upstream(getEmrrmRltmUsefulSckbdInfoInqire=beds, **{"basic:A2300004": basic})
    ers = await live(up).get_er_beds("Chungju")
    assert [e.name for e in ers] == ["건국대학교충주병원"]  # no coordinates: dropped
    konkuk = ers[0]
    assert konkuk.hvicc is None
    assert konkuk.status is DataStatus.UNCERTAIN  # update time unknown
    assert konkuk.tel == "043-840-8593"  # falls back to dutyTel1 from the basic info


@pytest.mark.asyncio
async def test_result_code_error_without_key():
    bad = "<response><header><resultCode>03</resultCode><resultMsg>NODATA_ERROR</resultMsg></header></response>"
    with pytest.raises(ProviderError, match="UPSTREAM_RESULT_03") as exc:
        await live(Upstream(getEmrrmRltmUsefulSckbdInfoInqire=bad)).get_er_beds("Chungju")
    assert FAKE_KEY not in str(exc.value) and "http" not in str(exc.value)


@pytest.mark.asyncio
async def test_gateway_error_redacts_an_echoed_key():
    bad = (
        "<OpenAPI_ServiceResponse><cmmMsgHeader><errMsg>SERVICE ERROR</errMsg>"
        f"<returnAuthMsg>SERVICE_KEY_IS_NOT_REGISTERED_ERROR {FAKE_KEY}</returnAuthMsg>"
        "<returnReasonCode>30</returnReasonCode></cmmMsgHeader></OpenAPI_ServiceResponse>"
    )
    with pytest.raises(ProviderError, match="UPSTREAM_RESULT_30") as exc:
        await live(Upstream(getParmacyLcinfoInqire=bad)).get_pharmacies(PATIENT)
    assert FAKE_KEY not in str(exc.value)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("response", "code"),
    [(httpx.Response(500, text="oops"), "UPSTREAM_HTTP_500"), (httpx.Response(200, text="not xml"), "BAD_RESPONSE")],
)
async def test_http_error_and_non_xml(response, code):
    provider = LiveProvider(er_key=FAKE_KEY, transport=httpx.MockTransport(lambda r: response))
    with pytest.raises(ProviderError, match=code) as exc:
        await provider.get_er_beds("Chungju")
    assert FAKE_KEY not in str(exc.value)


@pytest.mark.asyncio
async def test_call_timeout_is_provider_error():
    def hang(request):
        raise httpx.ReadTimeout("timed out", request=request)

    provider = LiveProvider(er_key=FAKE_KEY, transport=httpx.MockTransport(hang))
    with pytest.raises(ProviderError, match="UPSTREAM_TIMEOUT") as exc:
        await provider.get_pharmacies(PATIENT)
    assert FAKE_KEY not in str(exc.value) and "http" not in str(exc.value)


@pytest.mark.asyncio
async def test_tool_budget_timeout(monkeypatch):
    monkeypatch.setattr(providers, "TOOL_BUDGET_S", 0.05)

    async def slow(request):
        await asyncio.sleep(1)
        return httpx.Response(200, text=sample("er_beds.xml"))

    provider = LiveProvider(er_key=FAKE_KEY, transport=httpx.MockTransport(slow))
    with pytest.raises(ProviderError, match="tool budget"):
        await provider.get_er_beds("Chungju")


@pytest.mark.asyncio
async def test_beds_cached_60s_basics_24h():
    now = [1000.0]
    up = Upstream()
    provider = live(up, clock=lambda: now[0])
    await provider.get_er_beds("Chungju")
    now[0] += 59
    await provider.get_er_beds("Chungju")
    assert up.count("getEmrrmRltmUsefulSckbdInfoInqire") == 1
    now[0] += 2  # beds expired, basics still cached
    await provider.get_er_beds("Chungju")
    assert up.count("getEmrrmRltmUsefulSckbdInfoInqire") == 2
    assert up.count("getEgytBassInfoInqire") == 2
    now[0] += 24 * 3600
    await provider.get_er_beds("Chungju")
    assert up.count("getEgytBassInfoInqire") == 4


@pytest.mark.asyncio
async def test_errors_are_not_cached():
    bad = "<response><header><resultCode>99</resultCode><resultMsg>x</resultMsg></header></response>"
    up = Upstream(getEmrrmRltmUsefulSckbdInfoInqire=bad)
    provider = live(up)
    with pytest.raises(ProviderError):
        await provider.get_er_beds("Chungju")
    up.responses["getEmrrmRltmUsefulSckbdInfoInqire"] = sample("er_beds.xml")
    assert len(await provider.get_er_beds("Chungju")) == 2


@pytest.mark.asyncio
async def test_pharmacies_parse_open_and_sorted():
    up = Upstream()
    found = await live(up).get_pharmacies(PATIENT, at_time="12:00")
    assert found and all(p.source == "LIVE" and p.is_open is True for p in found)
    assert [p.distance_km for p in found] == sorted(p.distance_km for p in found)
    first = found[0]
    assert (first.name, first.distance_km, first.open_until) == ("세원약국", 0.24, "19:30")
    assert first.location.name == "충청북도 충주시 연수상가3길 6, (연수동)"
    params = up.calls[0].url.params
    assert (params["WGS84_LAT"], params["WGS84_LON"], params["serviceKey"]) == ("36.99", "127.93", FAKE_KEY)


@pytest.mark.asyncio
async def test_pharmacies_closed_dropped_and_missing_hours_unknown():
    xml = edit(sample("pharmacies_radius.xml"), "C2300574", startTime=None, endTime=None)
    found = await live(Upstream(getParmacyLcinfoInqire=xml)).get_pharmacies(PATIENT, at_time="23:45")
    by_name = {p.name: p for p in found}
    assert by_name["세원약국"].is_open is None and by_name["세원약국"].open_until is None
    # 23:45: only 이수약국 (0900-2400) is open; 안재경약국 closed at 23:30 and the rest earlier
    assert {p.name: p.open_until for p in found if p.is_open} == {"이수약국": "00:00"}
    assert set(by_name) == {"세원약국", "이수약국"}


def test_nmc_hours_helpers():
    assert parse_nmc_hhmm("0830") == time(8, 30)
    assert parse_nmc_hhmm("2400") == time(0, 0)
    assert parse_nmc_hhmm("2600") == time(2, 0)  # past midnight
    assert parse_nmc_hhmm("8:30") is None and parse_nmc_hhmm(None) is None
    assert open_status(time(3, 0), time(0, 0), time(0, 0)) is True  # 0000-2400
    assert open_status(time(1, 0), time(18, 0), time(2, 0)) is True  # crosses midnight
    assert open_status(time(7, 0), time(8, 30), time(19, 0)) is False
    assert open_status(time(7, 0), None, time(19, 0)) is None


def test_region_stages():
    assert region_stages("Chungju") == ("충청북도", "충주시")
    assert region_stages("") == ("충청북도", "충주시")
    assert region_stages("서울특별시 강남구") == ("서울특별시", "강남구")
    with pytest.raises(ProviderError, match="UNKNOWN_REGION"):
        region_stages("Atlantis")


@pytest.mark.asyncio
async def test_otc_is_static():
    assert await live(Upstream()).get_otc(Category.CRITICAL) == []


def test_provider_selection_and_key_fallback(monkeypatch):
    monkeypatch.delenv("EM_PROVIDER", raising=False)
    assert isinstance(get_provider(), MockProvider)
    monkeypatch.setenv("EM_PROVIDER", "live")
    monkeypatch.setenv("EM_DATA_GO_KR_KEY", "er%2Bkey")  # encoded key is decoded once
    monkeypatch.delenv("EM_DATA_GO_KR_KEY_PHARMACY", raising=False)
    provider = get_provider()
    assert isinstance(provider, LiveProvider)
    assert provider._er_key == provider._ph_key == "er+key"
    monkeypatch.setenv("EM_DATA_GO_KR_KEY_PHARMACY", "ph-key")
    assert get_provider()._ph_key == "ph-key"


@pytest.mark.asyncio
async def test_none_open_lists_three_nearest_closed_with_closing_time():
    found = await live(Upstream()).get_pharmacies(PATIENT, at_time="02:00")  # sample: all close by 24:00
    assert [(p.name, p.is_open, p.open_until) for p in found] == [
        ("세원약국", False, "19:30"), ("안재경약국", False, "23:30"), ("이수약국", False, "00:00"),
    ]


@pytest.mark.asyncio
async def test_unknown_hours_stay_listed_next_to_closed():
    xml = edit(sample("pharmacies_radius.xml"), "C2300572", startTime=None, endTime=None)
    found = await live(Upstream(getParmacyLcinfoInqire=xml)).get_pharmacies(PATIENT, at_time="02:00")
    by_name = {p.name: (p.is_open, p.open_until) for p in found}
    assert by_name["안재경약국"] == (None, None)  # hours unknown: shown, never dropped
    assert [p.is_open for p in found].count(False) == 3
