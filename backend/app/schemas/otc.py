"""API DTOs for GET /otc/{cat}."""

from __future__ import annotations

from pydantic import BaseModel, Field

from backend.app.models.enums import Category

DISCLAIMER = "Generic first-aid items only. Not medical advice. In an emergency call 119."


class OtcResponse(BaseModel):
    category: Category = Field(description="Requested category.")
    items: list[str] = Field(description="Generic first-aid items; empty for critical.")
    call_119: bool = Field(description="True for critical: call 119 instead of going to a pharmacy.")
    disclaimer: str = Field(default=DISCLAIMER, description="Always shown with the items.")
