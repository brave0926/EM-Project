"""First-aid card as sent to clients (POST /api/triage `first_aid`, SSE `first_aid` event)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from backend.app.models.enums import Language
from backend.app.models.first_aid import FirstAidKind


class FirstAidItemSchema(BaseModel):
    id: str = Field(description="Stable knowledge-base id, e.g. burn.cool.")
    text: str


class FirstAidSourceSchema(BaseModel):
    id: str
    publisher: str
    title: str
    url: str = Field(description='Official page, or "UNVERIFIED".')
    verified: bool
    note: str | None = None


class FirstAidCardSchema(BaseModel):
    entry: str = Field(description='Knowledge-base entry: a category, or "generic" (no specific guide).')
    kind: FirstAidKind = Field(description="standard; minimal (RED / high risk, no products); generic.")
    language: Language
    steps: list[FirstAidItemSchema] = Field(description="What to do now, in order.")
    do_not: list[FirstAidItemSchema]
    warning_signs: list[FirstAidItemSchema] = Field(description="Go to the ER / call 119 if any of these.")
    otc_types: list[FirstAidItemSchema] = Field(description="Product types that may help (no brands, no doses).")
    otc_note: str | None = Field(description="Use as labelled; ask a pharmacist. Set when otc_types is not empty.")
    escalate: str | None = Field(description="Set when the user's text names a warning sign.")
    matched_warning_signs: list[str]
    no_specific: str | None = Field(description='"No specific guide for this case" (generic entry only).')
    not_medical_advice: str
    sources: list[FirstAidSourceSchema]
    reviewed: bool = Field(description="False: draft text in this language, not reviewed by a human.")
    selected_by: Literal["kb", "llm"] = Field(description="llm: steps/products narrowed to ids the LLM picked.")
