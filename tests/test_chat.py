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


@pytest.mark.parametrize("kind", list(ChatKind))
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
