"""Triage stream events (domain). One event per SSE message; `event` is the SSE event name."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field

from backend.app.models.domain import ERFacility, Location, LocationSource, PharmacyFacility
from backend.app.models.enums import Category, ChatKind, Language, Notice, Patient, Severity
from backend.app.models.first_aid import FirstAidCard
from backend.app.models.llm import LlmStats


class StreamLocation(Location):
    source: LocationSource


class TriageEvent(BaseModel):
    event: Literal["triage"] = "triage"
    severity: Severity
    category: Category
    call_119: bool
    patient: Patient = Patient.UNKNOWN  # who is hurt (self/other/unknown): wording only
    language: Language
    location: StreamLocation
    at_time: str | None  # local time for pharmacy hours; None for critical cases
    prompt_119: str | None  # the 119 line in the user's language, for RED only
    t_ms: int = Field(ge=0)


class ChatEvent(BaseModel):
    """Small talk ("hi", "thanks", "who are you"): an assistant reply instead of a triage. Comes first
    and alone, then `done`; no triage, facilities or advice follow."""

    event: Literal["chat"] = "chat"
    kind: ChatKind
    language: Language
    reply: str
    t_ms: int = Field(ge=0)


class ContextEvent(BaseModel):
    """Only when the LLM filled what the rules missed: the place (a known place) and/or the time."""

    event: Literal["context"] = "context"
    location: StreamLocation
    at_time: str | None
    t_ms: int = Field(ge=0)


class FirstAidEvent(FirstAidCard):
    """The curated first-aid card (steps, do_not, warning_signs, otc_types, sources), when loaded."""

    event: Literal["first_aid"] = "first_aid"
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
    llm: LlmStats = Field(default_factory=LlmStats)  # extract_ms, rewrite_ms, outcome (off when no call)


StreamEvent = Annotated[
    ChatEvent | TriageEvent | ContextEvent | ErEvent | PharmacyEvent | FirstAidEvent | NoticeEvent | AdviceEvent | DoneEvent,
    Field(discriminator="event"),
]
