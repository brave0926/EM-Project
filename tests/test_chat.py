"""Small talk ("what's up", "thanks", "who are you") gets an assistant reply instead of a triage."""

import pytest

from backend.app.graph.triage_graph import stream_updates
from backend.app.models.enums import ChatKind, Language
from backend.app.services import chat_service
from backend.app.services.chat_service import detect_chat
from backend.app.services.triage_stream_service import stream_triage


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("what's up", ChatKind.GREETING), ("What's up?", ChatKind.GREETING), ("hi", ChatKind.GREETING),
        ("Hello!", ChatKind.GREETING), ("hey bro", ChatKind.GREETING), ("how are you", ChatKind.HOW_ARE_YOU),
        ("hi, how are you?", ChatKind.HOW_ARE_YOU), ("ok thanks", ChatKind.THANKS), ("who are you", ChatKind.ABOUT),
        ("what can you do?", ChatKind.ABOUT), ("bye", ChatKind.BYE), ("good night", ChatKind.BYE),
        ("привет", ChatKind.GREETING), ("Привет, как дела?", ChatKind.HOW_ARE_YOU), ("спасибо", ChatKind.THANKS),
        ("кто ты", ChatKind.ABOUT), ("пока", ChatKind.BYE),
        ("你好", ChatKind.GREETING), ("你好吗", ChatKind.HOW_ARE_YOU), ("谢谢", ChatKind.THANKS),
        ("你是谁", ChatKind.ABOUT), ("再见", ChatKind.BYE),
        ("안녕하세요", ChatKind.GREETING), ("감사합니다", ChatKind.THANKS), ("누구세요", ChatKind.ABOUT),
        ("안녕히계세요", ChatKind.BYE),
    ],
)
def test_small_talk_is_detected(text, kind):
    assert detect_chat(text) is kind


@pytest.mark.parametrize(
    "text",
    [
        "help", "help!", "hi, I burned my hand", "hello my child has a fever", "hi chest pain", "bye I'm bleeding",
        "how are you, I fell down", "hi near Chungju station", "my leg", "what", "asdf", "",
        "привет, у меня болит голова", "你好，我头疼", "안녕하세요 다쳤어요",
        "hi " * 30,  # too long
    ],
)
def test_anything_more_than_small_talk_goes_to_triage(text):
    assert detect_chat(text) is None


@pytest.mark.parametrize("kind", [k for k in ChatKind if k is not ChatKind.GENERAL])
@pytest.mark.parametrize("language", list(Language))
def test_every_reply_offers_help_and_119(kind, language):
    text = chat_service.reply(kind, language)
    assert "119" in text.splitlines()[-1]


@pytest.mark.asyncio
async def test_stream_sends_only_chat_then_done():
    events = [e async for e in stream_triage(stream_updates("what's up"))]
    assert [e.event for e in events] == ["chat", "done"]
    chat, done = events
    assert (chat.kind, chat.language) == (ChatKind.GREETING, Language.EN)
    assert chat.reply.startswith("Hi! I'm EM-Agent.")
    assert done.rt101_ok and done.rt105_ok and done.notices == []


@pytest.mark.asyncio
async def test_stream_reply_uses_requested_language():
    events = [e async for e in stream_triage(stream_updates("hi", language=Language.KO))]
    assert events[0].event == "chat" and events[0].language is Language.KO


@pytest.mark.asyncio
async def test_api_triage_small_talk(api):
    async with api() as client:
        body = (await client.post("/api/triage", json={"query": "thanks"})).json()
    assert body["chat"] == "thanks"
    assert (body["severity"], body["category"], body["location"], body["er"]) == (None, None, None, [])
    assert body["advice"].startswith("You're welcome!")


@pytest.mark.asyncio
async def test_api_triage_emergency_has_no_chat(api):
    async with api() as client:
        body = (await client.post("/api/triage", json={"query": "hi, I burned my hand"})).json()
    assert body["chat"] is None
    assert (body["category"], body["severity"]) == ("burn", "green")


# --- messages that are not small talk -------------------------------------------------------------

import asyncio  # noqa: E402
import json  # noqa: E402

from backend.app.clients.llm_client import LlmClient, set_llm_client  # noqa: E402
from backend.app.models.enums import Notice  # noqa: E402
from backend.app.services.chat_service import needs_triage  # noqa: E402


@pytest.mark.parametrize(
    "text",
    ["help", "my dad is acting strange", "my leg", "I need a doctor", "помогите", "мне плохо", "救命", "我不舒服",
     "도와주세요", "오늘 머리가 아파요", "Severe burn on my hand"],
)
def test_health_or_distress_words_go_to_triage(text):
    assert needs_triage(text)


@pytest.mark.parametrize("text", ["what's the weather", "tell me a joke", "asdf", "как погода", "今天天气怎么样", "오늘 날씨 어때"])
def test_non_medical_text_is_not_triaged(text):
    assert not needs_triage(text)


def test_unclear_safety_phrases_still_go_to_triage():
    """tests/test_classifier_safety.py UNCLEAR: text that may hide a problem is triaged (AMBER), not chatted.
    Blank text gets the UNCLEAR question; "hello" alone is small talk."""
    from tests.test_classifier_safety import UNCLEAR

    rest = [t for t in UNCLEAR if t.strip() and detect_chat(t) is None]
    assert rest and [t for t in rest if not needs_triage(t)] == []


@pytest.mark.parametrize("text", ["something is wrong", "something happened to my mom", "что-то случилось",
                                  "出事了", "怎么办", "큰일났어요", "어떡해"])
def test_something_is_wrong_goes_to_triage(text):
    assert needs_triage(text)


def test_every_first_aid_scenario_goes_to_triage():
    """The N6 scenario set (eval/scenarios/first_aid.yaml) is all health problems: none may get a chat reply."""
    import re
    from pathlib import Path

    texts = re.findall(r'"text": "([^"]+)"', Path("eval/scenarios/first_aid.yaml").read_text(encoding="utf-8"))
    assert len(texts) >= 30
    assert [t for t in texts if not needs_triage(t)] == []


async def _events(query, language=None):
    return [e async for e in stream_triage(stream_updates(query, language=language))]


@pytest.mark.asyncio
async def test_no_llm_unclear_text_asks_what_happened_without_ers():
    events = await _events("what's the weather")
    assert [e.event for e in events] == ["chat", "done"]
    assert events[0].kind is ChatKind.UNCLEAR
    assert events[0].reply.startswith("I couldn't find an injury or sickness") and "119" in events[0].reply


class ChatLlm(LlmClient):
    """chat() answers with `answer` (JSON text), after `delay` s, or raises when fail."""

    def __init__(self, answer=None, delay=0.0, fail=False):
        self.answer, self.delay, self.fail, self.calls = answer, delay, fail, 0

    async def chat(self, query, language):
        self.calls += 1
        await asyncio.sleep(self.delay)
        if self.fail:
            raise RuntimeError("model down")
        return self.answer

    async def rewrite_advice(self, advice, language):
        return advice

    async def extract_context(self, query, language):
        return json.dumps({"time": None, "place": None})

    async def select_items(self, query, language, items):
        return json.dumps({"ids": [items[0][0]]})


@pytest.fixture
def chat_llm():
    def install(**kwargs):
        fake = ChatLlm(**kwargs)
        set_llm_client(fake)
        return fake

    yield install
    set_llm_client(None)


@pytest.mark.asyncio
async def test_llm_answers_a_non_medical_message(chat_llm):
    fake = chat_llm(answer=json.dumps({"medical": False, "reply": "I can't check the weather, sorry. Do you need help?"}))
    events = await _events("what's the weather")
    assert [e.event for e in events] == ["chat", "done"]
    chat, done = events
    assert chat.kind is ChatKind.GENERAL
    assert chat.reply.splitlines() == ["I can't check the weather, sorry. Do you need help?",
                                       "If someone is hurt or sick, describe what happened. In an emergency call 119."]
    assert fake.calls == 1 and done.llm.chat_ms is not None


@pytest.mark.asyncio
async def test_llm_says_medical_runs_full_triage(chat_llm):
    chat_llm(answer=json.dumps({"medical": True, "reply": ""}))
    names = [e.event for e in await _events("my grandfather is not himself today")]
    assert names[0] == "triage" and {"er", "pharmacy", "advice", "done"} <= set(names)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kwargs",
    [{"fail": True}, {"answer": "not json"}, {"delay": 5.0},
     {"answer": json.dumps({"medical": False, "reply": "Take 500 mg of paracetamol."})},  # dose: invalid
     {"answer": json.dumps({"medical": False, "reply": ""})}],
)
async def test_llm_failure_or_bad_reply_falls_back_to_triage(chat_llm, kwargs):
    chat_llm(**kwargs)
    events = await _events("what's the weather")
    names = [e.event for e in events]
    assert "chat" not in names and "triage" in names and "er" in names
    assert Notice.LLM_FALLBACK in events[-1].notices


@pytest.mark.asyncio
async def test_llm_is_not_asked_about_small_talk_or_emergencies(chat_llm):
    fake = chat_llm(answer=json.dumps({"medical": False, "reply": "x"}))
    assert (await _events("hi"))[0].kind is ChatKind.GREETING
    assert (await _events("He is unconscious"))[0].event == "triage"
    assert fake.calls == 0
