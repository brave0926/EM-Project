import pytest

from eval.agents import AgentResult, plan_execute_agent, react_agent
from eval.fake_llm import FakeLLM

QUERY = "Severe burn on hand, near Chungju Station, 2 AM"

# Scaled-down latencies, no jitter: same ratio as the defaults, fast and deterministic.
LLM_LATENCY = 0.1
TOOL = {"tool_latency": 0.08, "tool_jitter": 0.0}


def fast_llm() -> FakeLLM:
    return FakeLLM(latency=LLM_LATENCY, jitter=0.0)


@pytest.mark.asyncio
async def test_plan_execute_fewer_calls_and_faster_than_react():
    react = await react_agent(QUERY, llm=fast_llm(), **TOOL)
    pe = await plan_execute_agent(QUERY, llm=fast_llm(), **TOOL)
    assert pe.llm_calls < react.llm_calls
    assert pe.total_seconds < react.total_seconds


@pytest.mark.asyncio
async def test_react_result_shape():
    r = await react_agent(QUERY, llm=fast_llm(), **TOOL)
    assert isinstance(r, AgentResult)
    assert r.answer
    assert r.llm_calls == 3
    assert r.tool_calls == 2
    assert r.tokens > 0 and r.cost > 0
    assert not r.stopped_by_limit
    # 3 sequential LLM calls + 2 sequential tools
    assert r.total_seconds >= 3 * LLM_LATENCY + 2 * TOOL["tool_latency"] - 0.01


@pytest.mark.asyncio
async def test_plan_execute_result_shape():
    r = await plan_execute_agent(QUERY, llm=fast_llm(), **TOOL)
    assert r.answer
    assert r.llm_calls == 2
    assert r.tool_calls == 2
    assert r.tokens > 0 and r.cost > 0
    # tools run in parallel: well under the sequential sum
    assert r.total_seconds < 2 * LLM_LATENCY + 2 * TOOL["tool_latency"]


@pytest.mark.asyncio
async def test_react_hard_iteration_limit():
    r = await react_agent(QUERY, llm=fast_llm(), max_iterations=1, **TOOL)
    assert r.stopped_by_limit
    assert r.llm_calls == 1
    assert r.tool_calls == 1


@pytest.mark.asyncio
async def test_shared_llm_counts_only_this_run():
    llm = fast_llm()
    await react_agent(QUERY, llm=llm, **TOOL)
    pe = await plan_execute_agent(QUERY, llm=llm, **TOOL)
    assert pe.llm_calls == 2
    assert llm.calls == 5
