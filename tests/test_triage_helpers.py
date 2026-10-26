import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from backend.app.clients.llm_client import LlmClient, set_llm_client
from backend.app.models.domain import ERFacility, Location, PharmacyFacility, TriageResult
from backend.app.models.enums import Category, Language, Notice, Severity
from backend.app.services.advice_service import _T, build_advice, data_notices, polish_advice
from backend.app.services.location_service import CITY_CENTRE, resolve_location
from backend.app.services.time_service import parse_time

LOC = Location(name="x", lat=36.97, lon=127.9)
NOW = datetime.now(timezone.utc)


def _er(name: str, hvec: int, fetched_at=NOW) -> ERFacility:
    return ERFacility(name=name, location=LOC, hvec=hvec, tel="043-000-0000", fetched_at=fetched_at, distance_km=2.0)


PHARM = PharmacyFacility(name="Night Pharmacy (mock)", location=LOC, open_until="04:00", tel="043-000-0711",
                         fetched_at=NOW, distance_km=0.3)
BURN_AMBER = TriageResult(category=Category.BURN, severity=Severity.AMBER, call_119=False)
CRITICAL = TriageResult(category=Category.CRITICAL, severity=Severity.RED, call_119=True)


# --- location -----------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("text", "name"),
    [
        ("burn near Chungju Station", "Chungju Station (approx.)"),
        ("충주역 근처에서 화상", "Chungju Station (approx.)"),
        ("忠州站附近", "Chungju Station (approx.)"),
        ("у вокзал Чхунджу", "Chungju Station (approx.)"),
        ("cut in Yeonsu-dong", "Yeonsu-dong (approx.)"),
    ],
)
def test_location_from_text(text, name):
    loc, source = resolve_location(text)
    assert (loc.name, source) == (name, "text")


def test_request_coordinates_win_over_text():
    loc, source = resolve_location("near Chungju Station", lat=36.9, lon=127.8)
    assert (loc.lat, loc.lon, source) == (36.9, 127.8, "request")


def test_unknown_place_defaults_to_city_centre():
    assert resolve_location("somewhere") == (CITY_CENTRE, "default")


# --- time ---------------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Severe burn, 2 AM", "02:00"), ("at 11 pm", "23:00"), ("12 am", "00:00"), ("12 pm", "12:00"),
        ("10:45 near the station", "10:45"),
        ("새벽 2시", "02:00"), ("밤 11시", "23:00"), ("오후 3시", "15:00"), ("밤 12시", "00:00"),
        ("凌晨2点", "02:00"), ("晚上9点", "21:00"),
        ("в 2 ночи", "02:00"), ("в 9 вечера", "21:00"),
        ("fever 39.5", None), ("열이 3시간째 나요", None), ("no time here", None),
    ],
)
def test_parse_time(text, expected):
    assert parse_time(text) == expected


# --- advice -------------------------------------------------------------------------------

@pytest.mark.parametrize("language", list(Language))
def test_every_language_has_every_template(language):
    assert _T[language].keys() == _T[Language.EN].keys()


def test_advice_lists_first_free_er_pharmacy_and_items():
    text = build_advice(Language.EN, BURN_AMBER, [_er("Full ER", 0), _er("Free ER", 3)], [PHARM],
                        ["Saline solution"], [])
    assert "Free ER" in text and "Full ER" not in text
    assert "Night Pharmacy (mock) (0.3 km, open until 04:00" in text
    assert "Saline solution" in text
    assert text.splitlines()[0] == _T[Language.EN]["amber"]
    assert text.splitlines()[-1] == _T[Language.EN]["disclaimer"]


@pytest.mark.parametrize("language", list(Language))
def test_critical_advice_calls_119_and_skips_pharmacy(language):
    text = build_advice(language, CRITICAL, [_er("Free ER", 3)], [PHARM], ["Saline solution"], [])
    assert text.startswith(_T[language]["red"]) and "119" in text.splitlines()[0]
    assert "Night Pharmacy" not in text and "Saline" not in text


def test_notices_are_spelled_out():
    text = build_advice(Language.KO, BURN_AMBER, [], [], [], [Notice.ER_UNAVAILABLE, Notice.LOCATION_DEFAULT])
    assert _T[Language.KO][Notice.ER_UNAVAILABLE] in text
    assert _T[Language.KO][Notice.LOCATION_DEFAULT] in text


def test_stale_data_gives_uncertain_notice():
    stale = _er("Old ER", 2, fetched_at=NOW - timedelta(minutes=200))
    assert data_notices([stale], []) == [Notice.DATA_UNCERTAIN]
    assert data_notices([_er("Fresh ER", 2)], [PHARM]) == []


# --- LLM rewrite is optional and never unsafe ---------------------------------------------

class _Llm(LlmClient):
    def __init__(self, reply=None, delay=0.0, fail=False):
        self.reply, self.delay, self.fail = reply, delay, fail

    async def rewrite_advice(self, advice, language):
        await asyncio.sleep(self.delay)
        if self.fail:
            raise RuntimeError("model down")
        return self.reply


@pytest.fixture
def llm():
    yield lambda **kw: set_llm_client(_Llm(**kw))
    set_llm_client(None)


@pytest.mark.asyncio
async def test_default_no_llm_keeps_template():
    assert await polish_advice("Call 119.", Language.EN) == "Call 119."


@pytest.mark.asyncio
async def test_llm_rewrite_is_used(llm):
    llm(reply="Clearer text. Call 119 if worse.")
    assert await polish_advice("Call 119.", Language.EN) == "Clearer text. Call 119 if worse."


@pytest.mark.asyncio
@pytest.mark.parametrize("kwargs", [{"fail": True}, {"reply": "no emergency number here"}, {"reply": ""},
                                    {"reply": "late 119", "delay": 1.5}])
async def test_bad_llm_falls_back_to_template(llm, kwargs):
    llm(**kwargs)
    assert await polish_advice("Template. Call 119.", Language.EN) == "Template. Call 119."
