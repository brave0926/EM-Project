"""First aid (domain): a guide from the curated knowledge base, and the card shown to the user.

FirstAidGuide is what em-mcp-server's get_first_aid returns (texts in one language, warning signs
with their match terms). FirstAidCard is what the user sees: match terms dropped, the escalation
line set when the user's text names a warning sign, items possibly narrowed by the LLM (ids only).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from backend.app.models.enums import Language

FirstAidKind = Literal["standard", "minimal", "generic"]  # minimal: RED / high risk; generic: no specific entry


class FirstAidStats(BaseModel):
    """Per request, for /metrics (no user text): which entry, how long, what happened."""

    entry: str | None = None  # None when the guide could not be loaded
    ms: int = Field(ge=0)
    outcome: Literal["ok", "unavailable"]
    generic: bool = False  # the case is outside the knowledge base (generic entry)
    escalated: bool = False
    selected_by: Literal["kb", "llm"] = "kb"


class FirstAidItem(BaseModel):
    id: str  # stable, e.g. "burn.cool"
    text: str


class WarningSign(FirstAidItem):
    """Terms that mean the user's text names this sign (EN whole words, RU regex stems, CJK substrings)."""

    match_en: list[str] = []
    match_ru: list[str] = []
    match_cjk: list[str] = []


class FirstAidSource(BaseModel):
    id: str
    publisher: str
    title: str
    url: str  # "UNVERIFIED" when the source could not be checked
    verified: bool
    note: str | None = None


class _GuideBase(BaseModel):
    entry: str  # category value, or "generic"
    kind: FirstAidKind
    language: Language
    steps: list[FirstAidItem]
    do_not: list[FirstAidItem]
    otc_types: list[FirstAidItem]  # product types only; empty for minimal and generic entries
    otc_note: str | None  # "use as labelled; ask a pharmacist ..." when otc_types is not empty
    no_specific: str | None  # "No specific guide for this case" (generic entry only)
    not_medical_advice: str
    sources: list[FirstAidSource]
    reviewed: bool  # False: draft text in this language, not reviewed by a human


class FirstAidGuide(_GuideBase):
    warning_signs: list[WarningSign]
    escalate_line: str  # shown when the user's text names a warning sign


class FirstAidCard(_GuideBase):
    warning_signs: list[FirstAidItem]
    escalate: str | None = None  # the escalation line, set when a warning sign was named
    matched_warning_signs: list[str] = Field(default_factory=list)  # ids
    selected_by: Literal["kb", "llm"] = "kb"  # llm: steps/otc narrowed to the ids the LLM picked
