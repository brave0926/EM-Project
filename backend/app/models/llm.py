"""LLM (domain): what the LLM may return and how each job went. No user text is kept here."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from backend.app.models.enums import LlmOutcome

# The only places the LLM may name; location_service maps them to coordinates (never invented).
KnownPlace = Literal["chungju_station", "yeonsu_dong", "city_hall"]
KNOWN_PLACES: tuple[KnownPlace, ...] = ("chungju_station", "yeonsu_dong", "city_hall")


class LlmContext(BaseModel):
    """Strict JSON from context extraction; anything else is ignored."""

    model_config = ConfigDict(extra="forbid")

    time: str | None = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")  # local "HH:MM"
    place: KnownPlace | None


class LlmJob(BaseModel):
    outcome: LlmOutcome
    ms: int | None = Field(default=None, ge=0)  # None when no call was made


class LlmStats(BaseModel):
    """Per request: shown in the stream's done event and kept in /metrics records."""

    extract_ms: int | None = Field(default=None, ge=0)
    rewrite_ms: int | None = Field(default=None, ge=0)
    outcome: LlmOutcome = LlmOutcome.OFF  # worst of the jobs that ran: error > timeout > invalid > ok
