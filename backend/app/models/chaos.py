"""Demo failure injection (domain): what /demo/chaos can switch on, per upstream tool."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field

# Limits re-exported for schemas/chaos.py (schemas may import models, not core).
from backend.app.core.config import CHAOS_DEFAULT_S, CHAOS_MAX_DELAY_MS, CHAOS_MAX_S  # noqa: F401

ChaosTool = Literal["er", "pharmacy"]
CHAOS_TOOLS: tuple[ChaosTool, ...] = ("er", "pharmacy")  # the tools with a breaker and a fallback cache


class ChaosTarget(StrEnum):
    ER = "er"
    PHARMACY = "pharmacy"
    ALL = "all"  # er + pharmacy (OTC is a static list without a breaker, never targeted)

    def tools(self) -> tuple[ChaosTool, ...]:
        return CHAOS_TOOLS if self is ChaosTarget.ALL else (self.value,)  # type: ignore[return-value]


class ChaosMode(StrEnum):
    OFF = "off"
    DELAY = "delay"  # wait delay_ms, then call upstream; past RT-102 it ends as TIMEOUT
    ERROR = "error"  # McpClientError TOOL_ERROR at once, upstream not called
    HANG = "hang"  # no answer until the RT-102 timeout, then TIMEOUT, upstream not called


class ChaosRule(BaseModel):
    mode: ChaosMode
    delay_ms: int | None = Field(default=None, ge=0)
    expires_at: float  # store clock (monotonic seconds)


class ChaosToolState(BaseModel):
    mode: ChaosMode
    delay_ms: int | None
    seconds_left: int = Field(ge=0)


class ChaosState(BaseModel):
    enabled: bool  # EM_DEMO_CHAOS=1
    active: bool  # any tool has a rule now
    tools: dict[str, ChaosToolState]
