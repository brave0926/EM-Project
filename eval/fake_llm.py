"""Fake LLM for benchmarks: fixed latency with jitter, canned reply, usage counters."""

from __future__ import annotations

import asyncio
import random

DEFAULT_RESPONSE = (
    "Severity: AMBER. Go to the nearest ER with free beds and call ahead. "
    "Not medical advice. In a critical emergency call 119."
)


def estimate_tokens(text: str) -> int:
    """Rough token estimate: about 4 characters per token."""
    if not text:
        return 0
    return max(1, len(text) // 4)


class FakeLLM:
    def __init__(
        self,
        latency: float = 1.0,
        jitter: float = 0.2,
        response: str = DEFAULT_RESPONSE,
        cost_per_1k_tokens: float = 0.003,
        seed: int | None = None,
    ) -> None:
        if latency < 0 or jitter < 0:
            raise ValueError("latency and jitter must be >= 0")
        self.latency = latency
        self.jitter = jitter
        self.response = response
        self.cost_per_1k_tokens = cost_per_1k_tokens
        self._rng = random.Random(seed)
        self.calls = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    @property
    def cost_usd(self) -> float:
        return self.total_tokens / 1000 * self.cost_per_1k_tokens

    async def call(self, prompt: str) -> str:
        delay = max(0.0, self.latency + self._rng.uniform(-self.jitter, self.jitter))
        await asyncio.sleep(delay)
        self.calls += 1
        self.prompt_tokens += estimate_tokens(prompt)
        self.completion_tokens += estimate_tokens(self.response)
        return self.response
