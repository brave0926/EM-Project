"""Shared data models for the EM-Agent backend.

Field names follow the NMC-like mock tools in eval/mock_tools.py
(hvec, tel, fetched_at, open_until, source).
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, model_validator

STALE_AFTER_MIN = 180  # RT-104
EARTH_RADIUS_KM = 6371.0088


class Severity(StrEnum):
    RED = "red"
    AMBER = "amber"
    GREEN = "green"


class Category(StrEnum):
    BURN = "burn"
    CUT = "cut"
    FEVER = "fever"
    CRITICAL = "critical"
    OTHER = "other"


class DataStatus(StrEnum):
    LIVE = "LIVE"
    CACHED = "CACHED"
    UNCERTAIN = "UNCERTAIN"


class Language(StrEnum):
    EN = "en"
    RU = "ru"
    ZH = "zh"
    KO = "ko"


def age_minutes(fetched_at: datetime, now: datetime | None = None) -> float:
    """Minutes since fetched_at. Naive datetimes are treated as UTC."""
    if fetched_at.tzinfo is None:
        fetched_at = fetched_at.replace(tzinfo=timezone.utc)
    now = now or datetime.now(timezone.utc)
    return (now - fetched_at).total_seconds() / 60


def freshness_status(
    status: DataStatus, fetched_at: datetime, now: datetime | None = None
) -> DataStatus:
    """RT-104: data older than 180 minutes is UNCERTAIN regardless of source."""
    if age_minutes(fetched_at, now) > STALE_AFTER_MIN:
        return DataStatus.UNCERTAIN
    return status


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


class TriageRequest(BaseModel):
    query: str = Field(min_length=1)
    language: Language | None = None  # auto-detected later if missing


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
    open_until: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")  # "HH:MM", local time


class TriageResponse(BaseModel):
    severity: Severity
    category: Category
    er: list[ERFacility] = Field(default_factory=list)
    pharmacies: list[PharmacyFacility] = Field(default_factory=list)
    advice: str
    call_119: bool
    total_ms: int = Field(ge=0)
