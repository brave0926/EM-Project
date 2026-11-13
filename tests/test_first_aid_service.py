"""First-aid tool, client and service (offline: in-process em-mcp-server, fake LLM)."""

import asyncio
import json

import pytest

from backend.app.clients.llm_client import LlmClient, set_llm_client
from backend.app.clients.mcp_client import McpClientError, get_mcp_client, set_mcp_client
from backend.app.models.domain import TriageResult
from backend.app.models.enums import Category, Language, Notice, Severity
from backend.app.services import first_aid_service, llm_service, request_timing

BURN_AMBER = TriageResult(category=Category.BURN, severity=Severity.AMBER, call_119=False)
BURN_GREEN = TriageResult(category=Category.BURN, severity=Severity.GREEN, call_119=False)
BURN_RED = TriageResult(category=Category.BURN, severity=Severity.RED, call_119=True)
CRITICAL = TriageResult(category=Category.CRITICAL, severity=Severity.RED, call_119=True)


class SelectLlm(LlmClient):
    def __init__(self, answer, delay=0.0):
        self.answer, self.delay, self.calls = answer, delay, 0

    async def rewrite_advice(self, advice, language):
        return advice

    async def select_items(self, query, language, items):
        self.calls += 1
        await asyncio.sleep(self.delay)
        return self.answer(items) if callable(self.answer) else self.answer


@pytest.mark.asyncio
@pytest.mark.parametrize("language", list(Language))
async def test_tool_returns_the_entry_in_each_language(use_mcp, language):
    use_mcp()
    guide = await get_mcp_client().get_first_aid(Category.BURN, language)
    assert guide.entry == "burn" and guide.language is language and guide.kind == "standard"
    assert [s.id for s in guide.steps][0] == "burn.cool" and guide.otc_types and guide.otc_note
    assert guide.sources[0].url.startswith("https://") and guide.reviewed is False
    assert all(w.match_en for w in guide.warning_signs)


@pytest.mark.asyncio
async def test_card_without_llm_is_the_full_entry(use_mcp):
    use_mcp()
    card, notices = await first_aid_service.get_card("small burn on my finger", BURN_GREEN, Language.EN)
    assert notices == [] and card.selected_by == "kb" and card.escalate is None
    assert [s.id for s in card.steps] == ["burn.cool", "burn.remove", "burn.cover"]
    assert "match_en" not in card.model_dump_json()  # match terms never reach the user


@pytest.mark.asyncio
@pytest.mark.parametrize(("query", "language", "sign"), [
    ("burn on my face", Language.EN, "burn.face"),
    ("ожог кислотой", Language.RU, "burn.chemical"),
    ("脸被烫伤了", Language.ZH, "burn.face"),
    ("얼굴에 화상", Language.KO, "burn.face"),
])
async def test_warning_sign_in_text_escalates(use_mcp, query, language, sign):
    use_mcp()
    card, _ = await first_aid_service.get_card(query, BURN_GREEN, language)
    assert sign in card.matched_warning_signs and "119" in card.escalate


@pytest.mark.asyncio
async def test_red_gets_the_minimal_entry_and_no_llm_call(use_mcp):
    use_mcp()
    llm = SelectLlm(json.dumps(["critical.call_119"]))
    set_llm_client(llm)
    for triage in (BURN_RED, CRITICAL):
        card, _ = await first_aid_service.get_card("burn, unconscious", triage, Language.KO)
        assert card.entry == "critical" and card.kind == "minimal" and card.otc_types == []
    assert llm.calls == 0


@pytest.mark.asyncio
async def test_failure_gives_notice_and_no_card():
    class Broken:
        async def get_first_aid(self, category, language, patient=None):
            raise McpClientError("UNAVAILABLE", "down")

    set_mcp_client(Broken())
    with request_timing.track() as timing:
        card, notices = await first_aid_service.get_card("burn", BURN_AMBER, Language.EN)
    assert card is None and notices == [Notice.FIRST_AID_UNAVAILABLE]
    assert timing.first_aid.outcome == "unavailable"


@pytest.mark.asyncio
async def test_valid_selection_narrows_steps_and_products(use_mcp):
    use_mcp()
    set_llm_client(SelectLlm(json.dumps({"ids": ["burn.cool", "burn.otc_dressing"]})))
    card, notices = await first_aid_service.get_card("burn", BURN_AMBER, Language.EN)
    assert card.selected_by == "llm" and notices == []
    assert [s.id for s in card.steps] == ["burn.cool"] and [o.id for o in card.otc_types] == ["burn.otc_dressing"]
    assert len(card.do_not) == 2 and len(card.warning_signs) == 3  # safety sections are never narrowed


@pytest.mark.asyncio
@pytest.mark.parametrize("answer", [
    "not json", "[]", '["burn.cool", "burn.cool"]', '["burn.cool", "made.up"]', '["burn.otc_dressing"]',
    '["cut.press"]', json.dumps(["burn.cool"] * 9), '{"ids": ["burn.cool"], "text": "x"}', "[1, 2]",
])
async def test_invalid_selection_keeps_the_full_entry(use_mcp, answer):
    use_mcp()
    set_llm_client(SelectLlm(answer))
    card, notices = await first_aid_service.get_card("burn", BURN_AMBER, Language.EN)
    assert card.selected_by == "kb" and len(card.steps) == 3 and notices == [Notice.LLM_FALLBACK]


@pytest.mark.asyncio
async def test_slow_selection_times_out_to_the_full_entry(use_mcp, monkeypatch):
    monkeypatch.setattr(llm_service, "LLM_TIMEOUT_S", 0.05)
    use_mcp()
    set_llm_client(SelectLlm(json.dumps(["burn.cool"]), delay=1.0))
    with request_timing.track() as timing:
        card, notices = await first_aid_service.get_card("burn", BURN_AMBER, Language.EN)
    assert card.selected_by == "kb" and len(card.steps) == 3 and notices == [Notice.LLM_FALLBACK]
    assert timing.llm_stats().select_ms <= 150 and timing.first_aid.outcome == "ok"


def test_parse_selection_rules():
    allowed, steps = ["a.s1", "a.s2", "a.otc"], ["a.s1", "a.s2"]
    assert llm_service.parse_selection('["a.s2", "a.otc"]', allowed, steps) == ["a.s2", "a.otc"]
    assert llm_service.parse_selection('{"ids": ["a.s1"]}', allowed, steps) == ["a.s1"]
    for bad in ('["a.otc"]', '[]', '["x"]', '["a.s1","a.s1"]', '{"ids": "a.s1"}', 'null', '"a.s1"'):
        with pytest.raises(llm_service._Invalid):
            llm_service.parse_selection(bad, allowed, steps)
