"""LLM jobs: validation, fallback, budget, rules-win, EM_LLM=off (offline: fake LlmClient, no key)."""

import asyncio
import json
from time import perf_counter

import pytest

from backend.app.clients import llm_client
from backend.app.clients.llm_client import AnthropicLlm, LlmClient, NoLlm, build_llm_client, set_llm_client
from backend.app.models.enums import Language, LlmOutcome, Notice
from backend.app.services import advice_service, chaos_service, llm_service, request_timing
from backend.app.models.chaos import ChaosMode, ChaosTarget

AMBER = "Severe burn on my hand, near Chungju Station, 2 AM"
NO_PLACE = "Severe burn on my hand, 2 AM"  # rules find the time, not the place
NO_TIME = "Severe burn on my hand, near Chungju Station"  # rules find the place, not the time
RED = "He is unconscious, not breathing, near Chungju Station"


class FakeLlm(LlmClient):
    """rewrite: callable(template) -> text; extract: JSON text. delay in s, fail raises."""

    def __init__(self, rewrite=lambda t: "Calm down and read this.\n" + t, extract=None, delay=0.0, fail=False):
        self.rewrite, self.extract, self.delay, self.fail = rewrite, extract, delay, fail
        self.calls = {"rewrite": 0, "extract": 0}

    async def _go(self, job):
        self.calls[job] += 1
        await asyncio.sleep(self.delay)
        if self.fail:
            raise RuntimeError("model down")

    async def rewrite_advice(self, advice, language):
        await self._go("rewrite")
        return self.rewrite(advice)

    async def extract_context(self, query, language):
        await self._go("extract")
        return self.extract if self.extract is not None else json.dumps({"time": None, "place": None})


@pytest.fixture
def llm():
    def install(**kwargs):
        fake = FakeLlm(**kwargs)
        set_llm_client(fake)
        return fake
    return install


async def triage(api, query, **extra):
    async with api() as client:
        response = await client.post("/api/triage", json={"query": query, **extra})
        assert response.status_code == 200
        return response.json()


async def stream(api, query):
    async with api() as client:
        response = await client.post("/api/triage/stream", json={"query": query})
    events = []
    for block in response.text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines())
        events.append((lines["event"], json.loads(lines["data"])))
    return events


# --- rewrite -----------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_valid_rewrite_is_used(api, llm):
    fake = llm()
    body = await triage(api, AMBER)
    assert body["advice"].startswith("Calm down and read this.\n") and fake.calls["rewrite"] == 1
    assert Notice.LLM_FALLBACK not in body["notices"] and fake.calls["extract"] == 0  # nothing missing


@pytest.mark.asyncio
async def test_rewrite_without_the_119_line_is_rejected_for_red(api, llm):
    llm(rewrite=lambda t: t.replace(advice_service.prompt_119(Language.EN), "It is probably fine. 119 if worse."))
    body = await triage(api, RED)
    assert body["severity"] == "red" and body["call_119"]  # the LLM never touches severity or 119
    assert advice_service.prompt_119(Language.EN) in body["advice"]  # template kept
    assert "probably fine" not in body["advice"] and Notice.LLM_FALLBACK in body["notices"]


@pytest.mark.asyncio
async def test_rewrite_dropping_a_facility_name_is_rejected(api, llm):
    template = (await triage(api, AMBER))["advice"]  # NoLlm: the template
    er_name = template.split("Nearest ER with free beds: ")[1].split(" (")[0]
    llm(rewrite=lambda t: t.replace(er_name, "the hospital"))
    body = await triage(api, AMBER)
    assert body["advice"] == template and Notice.LLM_FALLBACK in body["notices"]


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", ["", "   ", "Take 400 mg ibuprofen.\n{t}", "{t}" + "x" * 1000,
                                 "You probably have a second-degree burn.\n{t}"])
async def test_empty_dose_diagnosis_or_too_long_rewrite_is_rejected(api, llm, bad):
    template = (await triage(api, AMBER))["advice"]
    llm(rewrite=lambda t: bad.format(t=t))
    body = await triage(api, AMBER)
    assert body["advice"] == template and Notice.LLM_FALLBACK in body["notices"]


def test_check_rewrite_rules():
    template = "Go to ER A (tel 043-1). Not medical advice. In an emergency call 119."
    ok = "Please go to ER A now, phone 043-1. Not medical advice. Call 119 in an emergency."
    assert llm_service.check_rewrite(ok, template, ["ER A", "043-1"]) == ok
    for bad in ("Go to ER A. Call 119.", "Go to ER A, 043-1, take 2 tablets. 119", "ER A 043-1, no number"):
        with pytest.raises(llm_service._Invalid):
            llm_service.check_rewrite(bad, template, ["ER A", "043-1"])


@pytest.mark.parametrize("diagnosis", [
    "You most likely have a fracture.", "This is probably a heart attack.", "Diagnosis: second-degree burn.",
    "У вас, скорее всего, перелом.", "Диагноз: ожог второй степени.",
    "你可能患有骨折。", "诊断:二度烧伤。", "골절인 것 같습니다.", "진단: 2도 화상.",
])
def test_check_rewrite_rejects_diagnoses_in_all_languages(diagnosis):
    template = "Go to ER A (tel 043-1). Not medical advice. In an emergency call 119."
    with pytest.raises(llm_service._Invalid):
        llm_service.check_rewrite(f"{diagnosis} {template}", template, ["ER A", "043-1"])


# --- failures -> fallback, stream still complete -----------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize(("kwargs", "outcome"), [({"delay": 0.5}, "timeout"), ({"fail": True}, "error")])
async def test_timeout_or_error_falls_back_and_stream_completes(api, llm, monkeypatch, kwargs, outcome):
    monkeypatch.setattr(llm_service, "LLM_TIMEOUT_S", 0.1)
    llm(**kwargs)
    t0 = perf_counter()
    events = await stream(api, NO_PLACE)
    names = [n for n, _ in events]
    assert names[0] == "triage" and names[-2:] == ["advice", "done"] and "er" in names and "pharmacy" in names
    assert "context" not in names
    notices = [d["notice"] for n, d in events if n == "notice"]
    assert Notice.LLM_FALLBACK in notices and Notice.LOCATION_DEFAULT in notices
    done = events[-1][1]
    assert done["llm"]["outcome"] == outcome and done["rt105_ok"]
    assert done["llm"]["extract_ms"] is not None and done["llm"]["rewrite_ms"] is not None
    assert done["llm"]["extract_ms"] <= 150 and done["llm"]["rewrite_ms"] <= 150  # budget 100 ms + scheduling
    assert perf_counter() - t0 < 2.0  # each job capped at the (patched) budget
    advice = dict(events)["advice"]["advice"]
    assert "Calm down" not in advice and advice.endswith("Not medical advice. In an emergency call 119.")


@pytest.mark.asyncio
@pytest.mark.parametrize("kwargs", [{"delay": 1.5}, {"fail": True}, {"rewrite": lambda t: "Stay calm."}])
async def test_red_keeps_severity_and_119_when_the_llm_is_slow_failing_or_invalid(api, llm, kwargs):
    """Default LLM_TIMEOUT_S (not patched): a slow rewrite is cut at the budget."""
    template = (await triage(api, RED))["advice"]
    fake = llm(**kwargs)
    t0 = perf_counter()
    events = await stream(api, RED)
    elapsed = perf_counter() - t0
    data = dict(events)
    assert data["triage"]["severity"] == "red" and data["triage"]["call_119"]
    assert data["advice"]["advice"] == template and advice_service.prompt_119(Language.EN) in template
    assert Notice.LLM_FALLBACK in [d["notice"] for n, d in events if n == "notice"]
    llm_stats = data["done"]["llm"]
    assert fake.calls == {"rewrite": 1, "extract": 0}  # RED: place in the text, time not needed
    assert llm_stats["rewrite_ms"] <= llm_service.LLM_TIMEOUT_S * 1000 + 50
    assert elapsed < llm_service.LLM_TIMEOUT_S + 1.5 and data["done"]["rt105_ok"]


@pytest.mark.asyncio
@pytest.mark.parametrize("raw", ["not json", '{"time": "25:00", "place": null}', '{"time": null, "place": "seoul"}',
                                 '{"time": null, "place": null, "lat": 37.5}', "[]"])
async def test_invalid_extraction_is_ignored(api, llm, raw):
    llm(extract=raw)
    body = await triage(api, NO_PLACE)
    assert body["location_source"] == "default" and body["at_time"] == "02:00"
    assert Notice.LLM_FALLBACK in body["notices"] and Notice.LOCATION_DEFAULT in body["notices"]


@pytest.mark.asyncio
async def test_no_call_when_rt105_is_too_close():
    fake = FakeLlm()
    set_llm_client(fake)
    with request_timing.track() as timing:
        timing.started = perf_counter() - 5.8  # 0.2 s left, below the 0.3 s reserve
        text, job = await llm_service.rewrite_advice("Template. Call 119.", Language.EN)
    assert text == "Template. Call 119." and job.outcome is LlmOutcome.TIMEOUT and fake.calls["rewrite"] == 0


# --- extraction: fills only what the rules missed ----------------------------------------

@pytest.mark.asyncio
async def test_extraction_fills_a_missing_place(api, llm):
    fake = llm(extract=json.dumps({"time": "05:00", "place": "yeonsu_dong"}))
    events = await stream(api, NO_PLACE)
    names = [n for n, _ in events]
    assert names[:2] == ["triage", "context"] and fake.calls["extract"] == 1
    triage_ev, context = events[0][1], events[1][1]
    assert triage_ev["location"]["source"] == "default"  # the first event never waits for the LLM
    assert context["location"]["name"] == "Yeonsu-dong (approx.)" and context["location"]["source"] == "llm"
    assert context["at_time"] == "02:00"  # rules found "2 AM": the LLM's 05:00 is ignored
    notices = [d["notice"] for n, d in events if n == "notice"]
    assert Notice.LOCATION_DEFAULT not in notices and Notice.LLM_FALLBACK not in notices


@pytest.mark.asyncio
async def test_extraction_fills_a_missing_time_but_rules_keep_the_place(api, llm):
    llm(extract=json.dumps({"time": "03:00", "place": "yeonsu_dong"}))
    body = await triage(api, NO_TIME)
    assert body["location"]["name"] == "Chungju Station (approx.)" and body["location_source"] == "text"
    assert body["at_time"] == "03:00"


@pytest.mark.asyncio
async def test_rules_complete_means_no_extraction_call(api, llm):
    fake = llm(extract=json.dumps({"time": "05:00", "place": "yeonsu_dong"}))
    body = await triage(api, AMBER, lat=36.99, lon=127.93)
    assert fake.calls["extract"] == 0 and body["location_source"] == "request" and body["at_time"] == "02:00"


# --- EM_LLM=off and the client factory -------------------------------------------------------

@pytest.mark.asyncio
async def test_llm_off_is_never_called_and_unchanged(api, monkeypatch):
    monkeypatch.setenv("EM_LLM", "off")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-not-used")
    set_llm_client(None)
    assert isinstance(llm_client.get_llm_client(), NoLlm)
    events = await stream(api, NO_PLACE)
    names = [n for n, _ in events]
    assert names[:2] == ["triage", "notice"] and events[1][1]["notice"] == Notice.LOCATION_DEFAULT  # as before
    assert "context" not in names
    assert events[-1][1]["llm"] == {"extract_ms": None, "rewrite_ms": None, "outcome": "off"}
    body = await triage(api, NO_PLACE)
    assert Notice.LLM_FALLBACK not in body["notices"]


class SpyLlm(FakeLlm):
    enabled = False  # what NoLlm reports: the services must never call it


@pytest.mark.asyncio
async def test_disabled_client_is_never_called(api):
    spy = SpyLlm(fail=True)
    set_llm_client(spy)
    for query in (AMBER, NO_PLACE, NO_TIME, RED):
        await stream(api, query)
        body = await triage(api, query)
        assert Notice.LLM_FALLBACK not in body["notices"]
    assert spy.calls == {"rewrite": 0, "extract": 0}


def test_client_factory(monkeypatch):
    assert isinstance(build_llm_client(), NoLlm)  # nothing set
    monkeypatch.setenv("EM_LLM", "anthropic")
    assert isinstance(build_llm_client(), NoLlm)  # no key -> off, not an error
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-not-used")
    client = build_llm_client()
    assert isinstance(client, AnthropicLlm) and client.model == "claude-haiku-5-5"  # no network call made
    monkeypatch.setenv("EM_LLM_MODEL", "claude-sonnet-5-5")
    assert build_llm_client().model == "claude-sonnet-5-5"


# --- chaos and metrics -------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_chaos_llm_error_gives_the_template(api, llm, monkeypatch):
    monkeypatch.setenv("EM_DEMO_CHAOS", "1")
    template = (await triage(api, AMBER))["advice"]
    llm()
    chaos_service.set_chaos(ChaosTarget.LLM, ChaosMode.ERROR)
    body = await triage(api, AMBER)
    assert body["advice"] == template and Notice.LLM_FALLBACK in body["notices"]
    assert chaos_service.get_state().tools["llm"].mode is ChaosMode.ERROR
    assert chaos_service.get_state().tools["er"].mode is ChaosMode.OFF  # "llm" never touches the data tools


@pytest.mark.asyncio
async def test_metrics_count_llm_outcomes_without_user_text(api, llm):
    llm(extract=json.dumps({"time": None, "place": "city_hall"}))
    await triage(api, NO_PLACE)
    llm(fail=True)
    await triage(api, NO_PLACE)
    set_llm_client(NoLlm())
    await triage(api, NO_PLACE)
    async with api() as client:
        body = (await client.get("/metrics", params={"recent": 3})).json()
    assert body["llm"]["outcomes"] == {"ok": 1, "timeout": 0, "invalid": 0, "error": 1, "off": 1}
    assert body["llm"]["extract_ms"]["count"] == 2 and body["llm"]["rewrite_ms"]["count"] == 2
    assert [r["llm_outcome"] for r in body["recent"]] == ["ok", "error", "off"]
    assert "burn" not in json.dumps(body).lower()


@pytest.mark.asyncio
@pytest.mark.parametrize("kwargs", [{"fail": True}, {"extract": "not json"}, {}])
async def test_logs_hold_no_user_text_and_no_key(api, llm, monkeypatch, caplog, kwargs):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-secret-123")
    llm(**kwargs)
    with caplog.at_level("DEBUG"):
        await stream(api, NO_PLACE)
        await triage(api, NO_PLACE)
    text = caplog.text.lower()
    assert "llm rewrite" in text  # the job line is logged
    assert "burn" not in text and "sk-test-secret" not in text and "model down" not in text
