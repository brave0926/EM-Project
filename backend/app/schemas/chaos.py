from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from backend.app.models.chaos import CHAOS_DEFAULT_S, CHAOS_MAX_DELAY_MS, CHAOS_MAX_S, ChaosMode, ChaosTarget

_STATE_EXAMPLE = {
    "enabled": True,
    "active": True,
    "tools": {
        "er": {"mode": "error", "delay_ms": None, "seconds_left": 58},
        "pharmacy": {"mode": "error", "delay_ms": None, "seconds_left": 58},
    },
}


class ChaosRequestSchema(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {"target": "all", "mode": "error", "duration_s": 60},
                {"target": "er", "mode": "delay", "delay_ms": 3000, "duration_s": 60},
                {"target": "pharmacy", "mode": "hang"},
                {"target": "llm", "mode": "error"},
                {"target": "all", "mode": "off"},
            ]
        }
    )

    target: ChaosTarget = Field(
        description="er, pharmacy, all (er + pharmacy) or llm (both LLM jobs; needs EM_LLM=anthropic). "
        "OTC is never targeted."
    )
    mode: ChaosMode = Field(
        description="off; delay (wait delay_ms, past 2 s it ends as TIMEOUT); error (TOOL_ERROR at once); "
        "hang (no answer until the RT-102 timeout, then TIMEOUT)."
    )
    delay_ms: int | None = Field(
        default=None, ge=0, le=CHAOS_MAX_DELAY_MS, description="Delay mode only; default 3000 ms."
    )
    duration_s: int = Field(
        default=CHAOS_DEFAULT_S, ge=1, le=CHAOS_MAX_S, description="Auto-off after this many seconds (max 300)."
    )


class ChaosToolStateSchema(BaseModel):
    mode: ChaosMode
    delay_ms: int | None
    seconds_left: int = Field(ge=0, description="Until the switch turns itself off; 0 when off.")


class ChaosStateSchema(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [_STATE_EXAMPLE]})

    enabled: bool = Field(description="EM_DEMO_CHAOS=1 on the server.")
    active: bool = Field(description="Any tool has failure injection on now.")
    tools: dict[str, ChaosToolStateSchema] = Field(description="Per tool (er, pharmacy, llm).")
