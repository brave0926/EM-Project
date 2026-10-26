"""LLM port. No model is wired yet: NoLlm returns the template unchanged.

A real client (e.g. Claude) implements LlmClient and is installed with set_llm_client().
No FastAPI, no mcp_server imports.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from backend.app.models.enums import Language


class LlmClient(ABC):
    @abstractmethod
    async def rewrite_advice(self, advice: str, language: Language) -> str:
        """Return a clearer version of the advice in the same language."""


class NoLlm(LlmClient):
    async def rewrite_advice(self, advice: str, language: Language) -> str:
        return advice


_shared: LlmClient = NoLlm()


def get_llm_client() -> LlmClient:
    return _shared


def set_llm_client(client: LlmClient | None) -> None:
    global _shared
    _shared = client or NoLlm()
