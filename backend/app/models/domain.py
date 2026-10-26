"""Domain entities. Field names follow the NMC-like mock tools in eval/mock_tools.py
(hvec, tel, fetched_at, open_until, source).
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from backend.app.models.enums import DataStatus
# Allowed exception to one-way imports: RT-104 is a model invariant (see CLAUDE.md).
from backend.app.services.freshness import freshness_status

HHMM_PATTERN = r"^([01]\d|2[0-3]):[0-5]\d$"  # local time "HH:MM"


class Location(BaseModel):
    name: str
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)


class _FacilityBase(BaseModel):
    name: str
    location: Location
    tel: str
    fetched_at: datetime
    source: Literal["MOCK", "LIVE"] = "MOCK"
    status: DataStatus = DataStatus.LIVE
    distance_km: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _apply_freshness(self) -> _FacilityBase:
        self.status = freshness_status(self.status, self.fetched_at)
        return self


class ERFacility(_FacilityBase):
    hvec: int = Field(ge=0)  # free ER beds (NMC field name)


class PharmacyFacility(_FacilityBase):
    open_until: str = Field(pattern=HHMM_PATTERN)  # "HH:MM", local time
