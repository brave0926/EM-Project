import time

import pytest

from eval.fake_llm import FakeLLM, estimate_tokens


@pytest.mark.asyncio
async def test_counts_tokens_and_cost():
    llm = FakeLLM(latency=0, jitter=0, response="abcdefgh", cost_per_1k_tokens=1.0)
    out = await llm.call("x" * 40)
    await llm.call("x" * 40)
    assert out == "abcdefgh"
    assert llm.calls == 2
    assert llm.prompt_tokens == 20
    assert llm.completion_tokens == 4
    assert llm.total_tokens == 24
    assert llm.cost_usd == pytest.approx(0.024)


@pytest.mark.asyncio
async def test_delay_in_range():
    llm = FakeLLM(latency=0.3, jitter=0.1, seed=1)
    t0 = time.perf_counter()
    await llm.call("hi")
    assert 0.19 <= time.perf_counter() - t0 <= 0.5


def test_estimate_tokens():
    assert estimate_tokens("") == 0
    assert estimate_tokens("ab") == 1
    assert estimate_tokens("a" * 400) == 100


def test_rejects_negative_latency():
    with pytest.raises(ValueError):
        FakeLLM(latency=-1)
