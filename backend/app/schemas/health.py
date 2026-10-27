from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class BreakerStatus(BaseModel):
    state: Literal["CLOSED", "OPEN", "HALF_OPEN"] = Field(description="OPEN: upstream skipped, saved data served.")
    failures: int = Field(ge=0, description="Consecutive failures.")
    last_error: str | None = Field(description="Last MCP error code (TIMEOUT, UNAVAILABLE, ...); no details.")


class HealthResponse(BaseModel):
    status: str = Field(description="'ok' when the service is up.")
    version: str = Field(description="API version.")
    breakers: dict[str, BreakerStatus] = Field(description="Circuit breaker per tool (er, pharmacy).")
