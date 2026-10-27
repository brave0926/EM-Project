"""API DTOs for GET /facilities/ph."""

from __future__ import annotations

from pydantic import BaseModel, Field, computed_field

from backend.app.models.domain import HHMM_PATTERN, PharmacyFacility
from backend.app.models.enums import DataStatus, Notice


class PharmacyFacilitiesQuery(BaseModel):
    lat: float = Field(ge=-90, le=90, description="User latitude.")
    lon: float = Field(ge=-180, le=180, description="User longitude.")
    at_time: str | None = Field(
        default=None, pattern=HHMM_PATTERN, description="Local time HH:MM (KST); default is now."
    )


class PharmacyFacilitiesResponse(BaseModel):
    at_time: str = Field(description="Local time (KST, HH:MM) the opening hours were checked at.")
    facilities: list[PharmacyFacility] = Field(description="Pharmacies open at at_time, nearest first.")
    notices: list[Notice] = Field(
        default_factory=list, description="FALLBACK_CACHE: live lookup failed, last saved data shown."
    )

    @computed_field(description="Number of facilities returned.")
    @property
    def count(self) -> int:
        return len(self.facilities)

    @computed_field(description="True if any item is UNCERTAIN (data older than 180 min, RT-104).")
    @property
    def any_uncertain(self) -> bool:
        return any(f.status is DataStatus.UNCERTAIN for f in self.facilities)
