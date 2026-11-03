"""Request-scoped timing collector. Pure: no I/O, no FastAPI; imports only core and models.

track() opens a RequestTiming for the current request (a ContextVar). The graph's node tasks copy
the context when they start, so fallback_service can note the tool-call and fallback times of
that request without passing anything through the services. Outside track() the notes only bump
the global fallback counter.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field


@dataclass
class RequestTiming:
    tools: dict[str, int] = field(default_factory=dict)  # tool -> ms of its upstream call
    fallback_ms: int | None = None  # slowest cache answer of this request


_current: ContextVar[RequestTiming | None] = ContextVar("em_request_timing", default=None)
_lock = threading.Lock()
_fallback_total = 0


@contextmanager
def track() -> Iterator[RequestTiming]:
    timing = RequestTiming()
    token = _current.set(timing)
    try:
        yield timing
    finally:
        try:
            _current.reset(token)
        except ValueError:  # closed from another context (e.g. a generator finalised elsewhere)
            pass


def note_tool(tool: str, ms: int) -> None:
    timing = _current.get()
    if timing is not None:
        timing.tools[tool] = ms


def note_fallback(ms: int) -> None:
    global _fallback_total
    with _lock:
        _fallback_total += 1
    timing = _current.get()
    if timing is not None:
        timing.fallback_ms = ms if timing.fallback_ms is None else max(timing.fallback_ms, ms)


def fallback_total() -> int:
    with _lock:
        return _fallback_total


def reset_fallback_total() -> None:
    global _fallback_total
    with _lock:
        _fallback_total = 0
