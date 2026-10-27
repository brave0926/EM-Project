"""Triage stream events (domain). One event per SSE message; `event` is the SSE event name."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field

from backend.app.models.domain import ERFacility, Location, LocationSource, PharmacyFacility
from backend.app.models.enums import Category, Language, Notice, Severity


class StreamLocation(Location):
    source: LocationSource


class TriageEvent(BaseModel):
    event: Literal["triage"] = "triage"
    severity: Severity
    category: Category
    call_119: bool
    language: Language
    location: StreamLocation
    at_time: str | None  # local time for pharmacy hours; None for critical cases
    prompt_119: str | None  # the 119 line in the user's language, for RED only
    t_ms: int = Field(ge=0)


class ErEvent(BaseModel):
    event: Literal["er"] = "er"
    facilities: list[ERFacility]
    t_ms: int = Field(ge=0)


class PharmacyEvent(BaseModel):
    event: Literal["pharmacy"] = "pharmacy"
    facilities: list[PharmacyFacility]
    otc: list[str]
    at_time: str | None
    t_ms: int = Field(ge=0)


class NoticeEvent(BaseModel):
    event: Literal["notice"] = "notice"
    notice: Notice
    t_ms: int = Field(ge=0)


class AdviceEvent(BaseModel):
    event: Literal["advice"] = "advice"
    language: Language
    advice: str
    t_ms: int = Field(ge=0)


class DoneEvent(BaseModel):
    event: Literal["done"] = "done"
    total_ms: int = Field(ge=0)
    stages: dict[str, int]  # ms from the start to each event: triage, er, pharmacy, advice
    notices: list[Notice]
    timed_out: bool  # the RT-105 cap cut the run short; advice is then the template
    rt101_ok: bool  # first event <= 1.5 s
    rt105_ok: bool  # whole stream <= 6 s


StreamEvent = Annotated[
    TriageEvent | ErEvent | PharmacyEvent | NoticeEvent | AdviceEvent | DoneEvent,
    Field(discriminator="event"),
]
