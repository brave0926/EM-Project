"""LLM port and clients. No FastAPI, no mcp_server imports; never logs the key or user text.

Four jobs only: chat (user query -> JSON {"medical", "reply"}: is it about health, and a short
reply if it is not), rewrite_advice (template advice -> clearer text, same language),
extract_context (user query -> JSON {"time", "place"}) and select_items (user query + first-aid
item ids from the knowledge base -> JSON {"ids": [...]}, ids only, never text). Clients return raw text; validation,
budgets and fallbacks live in services/llm_service.py.

    EM_LLM=anthropic + ANTHROPIC_API_KEY -> AnthropicLlm (EM_LLM_MODEL, default claude-haiku-5-5)
    anything else                         -> NoLlm (never called; rules and template only)
"""

from __future__ import annotations

import asyncio
import json
import os
from abc import ABC, abstractmethod
from typing import Any

import anthropic

from backend.app.clients.chaos import get_chaos_store
from backend.app.core.config import LLM_TIMEOUT_S, demo_chaos_enabled, llm_mode, llm_model
from backend.app.models.chaos import ChaosMode
from backend.app.models.enums import Language
from backend.app.models.llm import KNOWN_PLACES

LANGUAGE_NAMES = {Language.EN: "English", Language.RU: "Russian", Language.ZH: "Simplified Chinese",
                  Language.KO: "Korean"}

REWRITE_SYSTEM = """You rewrite first-aid guidance for a person in an emergency in Chungju, Korea.
Rewrite the text inside <advice> so it is clearer and calmer, in {language}.
Rules:
- Keep every facility name, distance, opening time and phone number exactly as written.
- Keep every instruction to call 119 and keep the last line (the disclaimer) with its meaning.
- Do not add any medical claim, diagnosis, drug, dose or treatment that is not in the text.
- Do not remove warnings.
- At most 600 characters. Output only the rewritten text: no preamble, no markdown."""

EXTRACT_SYSTEM = """Read an emergency message (English, Russian, Chinese or Korean) and return the clock
time and the place it states, as JSON.
- time: the local clock time the message names, as 24-hour "HH:MM" (e.g. "2 AM" -> "02:00"), else null.
- place: one of {places} if the message clearly refers to that place in Chungju, else null.
Never guess: if the message does not state it, use null."""

EXTRACT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "time": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        "place": {"anyOf": [{"type": "string", "enum": list(KNOWN_PLACES)}, {"type": "null"}]},
    },
    "required": ["time", "place"],
    "additionalProperties": False,
}


SELECT_SYSTEM = """You choose which first-aid items from a fixed list fit a person's emergency message.
Return JSON {{"ids": [...]}} with 1 to {max_ids} ids copied exactly from the list, in any order.
Choose only ids that appear in <items>. Never write advice, explanations or new ids."""
SELECT_MAX_IDS = 8


CHAT_SYSTEM = """You are EM-Agent, an emergency assistant for Chungju, Korea. You help people find the
nearest ER and open pharmacy and give first-aid steps.
Decide whether the user's message is about an injury, a sickness, a symptom, someone in danger or any
health problem, or could be. If in doubt, it is medical.
- Medical: return {{"medical": true, "reply": ""}}.
- Not medical: return {{"medical": false, "reply": "..."}} with a short, friendly reply in {language}
  (at most 300 characters) that answers the message naturally, then asks if they need help.
Never give medical advice, a diagnosis, a drug or a dose. No markdown."""

CHAT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"medical": {"type": "boolean"}, "reply": {"type": "string"}},
    "required": ["medical", "reply"],
    "additionalProperties": False,
}


def select_schema(ids: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {"ids": {"type": "array", "items": {"type": "string", "enum": ids}}},
        "required": ["ids"],
        "additionalProperties": False,
    }


class LlmError(Exception):
    """The LLM answered but not usably (refusal, no text). Message: a short code, never user text."""


class LlmClient(ABC):
    enabled: bool = True  # NoLlm: False -> the services never call it

    @abstractmethod
    async def rewrite_advice(self, advice: str, language: Language) -> str:
        """Return a clearer version of the advice in the same language."""

    async def extract_context(self, query: str, language: Language) -> str:
        """Return JSON text {"time": "HH:MM" | null, "place": <known place> | null}."""
        raise NotImplementedError

    async def select_items(self, query: str, language: Language, items: list[tuple[str, str]]) -> str:
        """Return JSON text {"ids": [...]} (or a plain list) with ids picked from items (id, text)."""
        raise NotImplementedError

    async def chat(self, query: str, language: Language) -> str:
        """Return JSON text {"medical": bool, "reply": str}; reply is empty when medical."""
        raise NotImplementedError


class NoLlm(LlmClient):
    enabled = False

    async def rewrite_advice(self, advice: str, language: Language) -> str:
        return advice

    async def extract_context(self, query: str, language: Language) -> str:
        return json.dumps({"time": None, "place": None})

    async def select_items(self, query: str, language: Language, items: list[tuple[str, str]]) -> str:
        return json.dumps({"ids": []})

    async def chat(self, query: str, language: Language) -> str:
        return json.dumps({"medical": True, "reply": ""})


class AnthropicLlm(LlmClient):
    """Claude via the official SDK. No retries: a job has LLM_TIMEOUT_S in total."""

    def __init__(self, api_key: str, model: str, timeout_s: float = LLM_TIMEOUT_S) -> None:
        self.model = model
        self._client = anthropic.AsyncAnthropic(api_key=api_key, max_retries=0, timeout=timeout_s)

    async def rewrite_advice(self, advice: str, language: Language) -> str:
        response = await self._client.messages.create(
            model=self.model,
            max_tokens=800,
            system=REWRITE_SYSTEM.format(language=LANGUAGE_NAMES[language]),
            thinking={"type": "disabled"},
            output_config={"effort": "low"},
            messages=[{"role": "user", "content": f"<advice>\n{advice}\n</advice>"}],
        )
        return _text(response)

    async def extract_context(self, query: str, language: Language) -> str:
        response = await self._client.messages.create(
            model=self.model,
            max_tokens=100,
            system=EXTRACT_SYSTEM.format(places=", ".join(KNOWN_PLACES)),
            thinking={"type": "disabled"},
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": EXTRACT_SCHEMA}},
            messages=[{"role": "user", "content": f"<message lang=\"{language.value}\">\n{query}\n</message>"}],
        )
        return _text(response)

    async def select_items(self, query: str, language: Language, items: list[tuple[str, str]]) -> str:
        listing = "\n".join(f"{item_id}: {text}" for item_id, text in items)
        response = await self._client.messages.create(
            model=self.model,
            max_tokens=200,
            system=SELECT_SYSTEM.format(max_ids=SELECT_MAX_IDS),
            thinking={"type": "disabled"},
            output_config={"effort": "low", "format": {"type": "json_schema",
                                                       "schema": select_schema([i for i, _ in items])}},
            messages=[{"role": "user", "content": f"<message lang=\"{language.value}\">\n{query}\n</message>\n"
                                                  f"<items>\n{listing}\n</items>"}],
        )
        return _text(response)

    async def chat(self, query: str, language: Language) -> str:
        response = await self._client.messages.create(
            model=self.model,
            max_tokens=300,
            system=CHAT_SYSTEM.format(language=LANGUAGE_NAMES[language]),
            thinking={"type": "disabled"},
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": CHAT_SCHEMA}},
            messages=[{"role": "user", "content": f"<message lang=\"{language.value}\">\n{query}\n</message>"}],
        )
        return _text(response)

    async def aclose(self) -> None:
        await self._client.close()


def _text(response: Any) -> str:
    if response.stop_reason == "refusal":
        raise LlmError("refusal")
    if response.stop_reason == "max_tokens":
        raise LlmError("max_tokens")  # cut off: incomplete text or JSON
    text = "".join(block.text for block in response.content if block.type == "text")
    if not text.strip():
        raise LlmError("empty")
    return text


class ChaosLlmClient(LlmClient):
    """Demo failure injection (/demo/chaos target "llm"). error: raise at once; hang: never answer
    (the service budget cuts it); delay: wait delay_ms, then the real call."""

    def __init__(self, inner: LlmClient) -> None:
        self._inner = inner

    async def _apply(self, call: Any) -> str:
        rule = get_chaos_store().rule("llm")
        if rule is None:
            return await call()
        if rule.mode is ChaosMode.ERROR:
            raise LlmError("injected error (demo chaos)")
        if rule.mode is ChaosMode.HANG:
            await asyncio.sleep(3600)
        await asyncio.sleep((rule.delay_ms or 0) / 1000)
        return await call()

    async def rewrite_advice(self, advice: str, language: Language) -> str:
        return await self._apply(lambda: self._inner.rewrite_advice(advice, language))

    async def extract_context(self, query: str, language: Language) -> str:
        return await self._apply(lambda: self._inner.extract_context(query, language))

    async def select_items(self, query: str, language: Language, items: list[tuple[str, str]]) -> str:
        return await self._apply(lambda: self._inner.select_items(query, language, items))

    async def chat(self, query: str, language: Language) -> str:
        return await self._apply(lambda: self._inner.chat(query, language))


def build_llm_client() -> LlmClient:
    """From the environment: AnthropicLlm only with EM_LLM=anthropic and a key, else NoLlm."""
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if llm_mode() == "anthropic" and key:
        return AnthropicLlm(api_key=key, model=llm_model())
    return NoLlm()


_shared: LlmClient | None = None


def get_llm_client() -> LlmClient:
    """App-wide client (lazy, from the environment). Wrapped for /demo/chaos while an llm rule is
    active (EM_DEMO_CHAOS=1 only); a disabled client is never wrapped, so EM_LLM=off stays off."""
    global _shared
    if _shared is None:
        _shared = build_llm_client()
    if _shared.enabled and demo_chaos_enabled() and get_chaos_store().rule("llm") is not None:
        return ChaosLlmClient(_shared)
    return _shared


def set_llm_client(client: LlmClient | None) -> None:
    """Install a client (tests); None rebuilds from the environment on next use."""
    global _shared
    _shared = client
