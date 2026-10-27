"""Use case: stream a triage run as typed events. Pure: no FastAPI, no graph import.

The controller passes in the graph's node updates (graph/triage_graph.stream_updates); this
service turns them into events, in the order the nodes finish:

    triage (rules only, first) -> notice* -> er / pharmacy (either order) -> notice* -> advice -> done

The whole stream is capped at RT-105: when the cap hits, the graph is closed (its running
workers are cancelled), missing workers get an UNAVAILABLE notice, the advice comes from the
template, and done reports rt105_ok=false. Closing this generator (client gone) closes the graph.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from time import perf_counter
from typing import Any

from backend.app.core.config import END_TO_END_S, TTFT_S
from backend.app.models.domain import TriageResult
from backend.app.models.enums import Language, Notice, Severity
from backend.app.models.stream import (
    AdviceEvent,
    DoneEvent,
    ErEvent,
    NoticeEvent,
    PharmacyEvent,
    StreamEvent,
    StreamLocation,
    TriageEvent,
)
from backend.app.services import advice_service


class _Run:
    """What the stream has seen so far."""

    def __init__(self, clock: Callable[[], float]) -> None:
        self._clock = clock
        self._t0 = clock()
        self.state: dict[str, Any] = {}
        self.notices: list[Notice] = []
        self.stages: dict[str, int] = {}
        self.first_ms: int | None = None

    def ms(self) -> int:
        return max(0, round((self._clock() - self._t0) * 1000))

    def elapsed_s(self) -> float:
        return self._clock() - self._t0

    def stamp(self, stage: str | None = None) -> int:
        t = self.ms()
        if self.first_ms is None:
            self.first_ms = t
        if stage:
            self.stages[stage] = t
        return t

    def new_notices(self, notices: list[Notice]) -> list[NoticeEvent]:
        fresh = [n for n in dict.fromkeys(notices) if n not in self.notices]
        self.notices += fresh
        return [NoticeEvent(notice=n, t_ms=self.stamp()) for n in fresh]


def _triage_event(run: _Run, update: dict[str, Any]) -> TriageEvent:
    triage: TriageResult = update["triage"]
    language: Language = update["language"]
    red = triage.severity is Severity.RED
    return TriageEvent(
        severity=triage.severity,
        category=triage.category,
        call_119=triage.call_119,
        language=language,
        location=StreamLocation(**update["location"].model_dump(), source=update["location_source"]),
        at_time=None if red else update.get("at_time"),
        prompt_119=advice_service.prompt_119(language) if red else None,
        t_ms=run.stamp("triage"),
    )


def _events(run: _Run, node: str, update: dict[str, Any]) -> list[StreamEvent]:
    run.state.update(update)
    notices = update.get("notices", [])
    if node == "triage":
        return [_triage_event(run, update), *run.new_notices(notices)]
    if node == "er_worker":
        return [ErEvent(facilities=update.get("er", []), t_ms=run.stamp("er")), *run.new_notices(notices)]
    if node == "pharmacy_worker":
        event = PharmacyEvent(
            facilities=update.get("pharmacies", []),
            otc=update.get("otc", []),
            at_time=run.state.get("at_time"),
            t_ms=run.stamp("pharmacy"),
        )
        return [event, *run.new_notices(notices)]
    if node == "advise":
        notice_events = run.new_notices(notices)
        advice = AdviceEvent(language=run.state["language"], advice=update["advice"], t_ms=run.stamp("advice"))
        return [*notice_events, advice]
    return []


def _cut_short(run: _Run) -> list[StreamEvent]:
    """RT-105 hit: report missing workers and give the template advice from what is known."""
    state = run.state
    if "triage" not in state:
        return []
    red = state["triage"].severity is Severity.RED
    missing = [] if "er" in state else [Notice.ER_UNAVAILABLE]
    if not red and "pharmacies" not in state:
        missing.append(Notice.PHARMACY_UNAVAILABLE)
    events: list[StreamEvent] = list(run.new_notices(missing))
    if "advice" not in run.stages:
        text = advice_service.build_advice(
            state["language"], state["triage"], state.get("er", []), state.get("pharmacies", []),
            state.get("otc", []), run.notices, state.get("requested_time"),
        )
        events.append(AdviceEvent(language=state["language"], advice=text, t_ms=run.stamp("advice")))
    return events


async def stream_triage(
    updates: AsyncIterator[dict[str, Any]],
    budget_s: float = END_TO_END_S,
    clock: Callable[[], float] = perf_counter,
) -> AsyncIterator[StreamEvent]:
    run = _Run(clock)
    timed_out = False
    try:
        while True:
            remaining = budget_s - run.elapsed_s()
            if remaining <= 0:
                timed_out = True
                break
            try:
                chunk = await asyncio.wait_for(anext(updates), remaining)
            except StopAsyncIteration:
                break
            except TimeoutError:
                timed_out = True
                break
            for node, update in chunk.items():
                for event in _events(run, node, update or {}):
                    yield event
    finally:
        aclose = getattr(updates, "aclose", None)
        if aclose is not None:
            await aclose()  # cancels workers still running (timeout or client gone)
    if timed_out:
        for event in _cut_short(run):
            yield event
    total = run.ms()
    yield DoneEvent(
        total_ms=total,
        stages=run.stages,
        notices=run.notices,
        timed_out=timed_out,
        rt101_ok=run.first_ms is not None and run.first_ms <= TTFT_S * 1000,
        rt105_ok=not timed_out and total <= END_TO_END_S * 1000,
    )
