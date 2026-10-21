"""ReAct vs Plan-Execute agents over FakeLLM and the mock tools.

FakeLLM returns a canned string, so tool choice is scripted here; the LLM
calls only contribute latency, call counts, tokens and cost.
"""

from __future__ import annotations

import asyncio
import time

from pydantic import BaseModel

from eval.fake_llm import FakeLLM
from eval.mock_tools import DEFAULT_JITTER, DEFAULT_LATENCY, er_beds, pharmacy

DEMO_REGION = "Chungju"
DEMO_LAT, DEMO_LON = 36.971, 127.899  # Chungju Station
TOOLS = ("er_beds", "pharmacy")
MAX_ITERATIONS = 6


class AgentResult(BaseModel):
    answer: str
    total_seconds: float
    llm_calls: int
    tokens: int
    cost: float
    tool_calls: int
    stopped_by_limit: bool = False


async def _run_tool(name: str, latency: float, jitter: float) -> str:
    if name == "er_beds":
        rows = await er_beds(DEMO_REGION, latency=latency, jitter=jitter)
        return "; ".join(f"{r.name} hvec={r.hvec} tel={r.tel}" for r in rows)
    rows = await pharmacy(DEMO_LAT, DEMO_LON, latency=latency, jitter=jitter)
    return "; ".join(f"{r.name} open_until={r.open_until} tel={r.tel}" for r in rows)


def _result(llm: FakeLLM, start: tuple[int, int, float], t0: float, answer: str,
            tool_calls: int, stopped_by_limit: bool = False) -> AgentResult:
    calls0, tokens0, cost0 = start
    return AgentResult(
        answer=answer,
        total_seconds=time.perf_counter() - t0,
        llm_calls=llm.calls - calls0,
        tokens=llm.total_tokens - tokens0,
        cost=llm.cost_usd - cost0,
        tool_calls=tool_calls,
        stopped_by_limit=stopped_by_limit,
    )


async def react_agent(
    query: str,
    *,
    llm: FakeLLM | None = None,
    tool_latency: float = DEFAULT_LATENCY,
    tool_jitter: float = DEFAULT_JITTER,
    max_iterations: int = MAX_ITERATIONS,
) -> AgentResult:
    """Think -> one tool -> think ... ; stops once both tools have been used."""
    llm = llm or FakeLLM()
    start = (llm.calls, llm.total_tokens, llm.cost_usd)
    t0 = time.perf_counter()
    observations: list[str] = []
    used: list[str] = []
    thought = ""

    for _ in range(max_iterations):
        prompt = f"Query: {query}\nObservations:\n" + "\n".join(observations)
        thought = await llm.call(prompt)
        pending = [t for t in TOOLS if t not in used]
        if not pending:
            return _result(llm, start, t0, thought, len(used))
        tool = pending[0]
        observations.append(f"{tool}: {await _run_tool(tool, tool_latency, tool_jitter)}")
        used.append(tool)

    return _result(llm, start, t0, thought, len(used), stopped_by_limit=True)


async def plan_execute_agent(
    query: str,
    *,
    llm: FakeLLM | None = None,
    tool_latency: float = DEFAULT_LATENCY,
    tool_jitter: float = DEFAULT_JITTER,
) -> AgentResult:
    """One LLM call plans, tools run in parallel, one LLM call answers."""
    llm = llm or FakeLLM()
    start = (llm.calls, llm.total_tokens, llm.cost_usd)
    t0 = time.perf_counter()

    await llm.call(f"Plan the tools needed for: {query}\nAvailable: {', '.join(TOOLS)}")
    plan = list(TOOLS)
    outputs = await asyncio.gather(*(_run_tool(t, tool_latency, tool_jitter) for t in plan))
    observations = "\n".join(f"{t}: {o}" for t, o in zip(plan, outputs))
    answer = await llm.call(f"Query: {query}\nObservations:\n{observations}\nWrite the answer.")
    return _result(llm, start, t0, answer, len(plan))
