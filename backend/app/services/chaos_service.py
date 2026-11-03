"""Use case: demo failure injection (/demo/chaos). Pure: no FastAPI, no I/O.

Writes rules into the chaos store (clients/chaos.py); the MCP client applies them per call.
Off unless EM_DEMO_CHAOS=1. Every activation expires after duration_s (default 60, max 300).
"""

from __future__ import annotations

import math

from backend.app.clients.chaos import get_chaos_store
from backend.app.core.config import (
    CHAOS_DEFAULT_DELAY_MS,
    CHAOS_DEFAULT_S,
    CHAOS_MAX_DELAY_MS,
    CHAOS_MAX_S,
    demo_chaos_enabled,
)
from backend.app.models.chaos import CHAOS_TOOLS, ChaosMode, ChaosRule, ChaosState, ChaosTarget, ChaosToolState


def enabled() -> bool:
    return demo_chaos_enabled()


def set_chaos(
    target: ChaosTarget, mode: ChaosMode, delay_ms: int | None = None, duration_s: float | None = None
) -> ChaosState:
    store = get_chaos_store()
    duration = min(max(duration_s if duration_s is not None else CHAOS_DEFAULT_S, 1), CHAOS_MAX_S)
    rule = None
    if mode is not ChaosMode.OFF:
        delay = None
        if mode is ChaosMode.DELAY:
            delay = min(max(delay_ms if delay_ms is not None else CHAOS_DEFAULT_DELAY_MS, 0), CHAOS_MAX_DELAY_MS)
        rule = ChaosRule(mode=mode, delay_ms=delay, expires_at=store.clock() + duration)
    for tool in target.tools():
        store.set(tool, rule)
    return get_state()


def reset() -> ChaosState:
    get_chaos_store().clear()
    return get_state()


def get_state() -> ChaosState:
    store = get_chaos_store()
    tools: dict[str, ChaosToolState] = {}
    for tool in CHAOS_TOOLS:
        rule = store.rule(tool)
        if rule is None:
            tools[tool] = ChaosToolState(mode=ChaosMode.OFF, delay_ms=None, seconds_left=0)
        else:
            left = math.ceil(max(0.0, rule.expires_at - store.clock()))
            tools[tool] = ChaosToolState(mode=rule.mode, delay_ms=rule.delay_ms, seconds_left=left)
    return ChaosState(enabled=enabled(), active=any(t.mode is not ChaosMode.OFF for t in tools.values()), tools=tools)
