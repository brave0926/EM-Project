"""API DTOs for POST /api/triage."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.app.models.domain import HHMM_PATTERN, ERFacility, Location, LocationSource, PharmacyFacility
from backend.app.models.enums import Category, Language, Notice, Severity

DEMO_QUERY = "Severe burn on my hand, near Chungju Station, 2 AM"


class TriageRequestSchema(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [{"query": DEMO_QUERY}]})

    query: str = Field(
        min_length=1, max_length=2000, description="Free-text emergency description (EN/RU/ZH/KO)."
    )
    language: Language | None = Field(default=None, description="Query language; auto-detected when omitted.")
    lat: float | None = Field(default=None, ge=-90, le=90, description="User latitude (with lon), e.g. from GPS.")
    lon: float | None = Field(default=None, ge=-180, le=180, description="User longitude (with lat).")
    at_time: str | None = Field(
        default=None, pattern=HHMM_PATTERN, description="Local time HH:MM (KST); else read from the text or now."
    )

    @model_validator(mode="after")
    def _lat_lon_together(self) -> TriageRequestSchema:
        if (self.lat is None) != (self.lon is None):
            raise ValueError("lat and lon must be given together")
        return self


_FETCHED = "2026-10-26T17:00:00Z"


class TriageResponseSchema(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "language": "en",
                    "severity": "amber",
                    "category": "burn",
                    "call_119": False,
                    "location": {"name": "Chungju Station (approx.)", "lat": 36.972, "lon": 127.9},
                    "location_source": "text",
                    "at_time": "02:00",
                    "er": [
                        {
                            "name": "Chungju Medical Center ER (mock)",
                            "location": {"name": "Anrim-dong (mock)", "lat": 36.981, "lon": 127.936},
                            "hvec": 5,
                            "tel": "043-000-0114",
                            "fetched_at": _FETCHED,
                            "source": "MOCK",
                            "status": "LIVE",
                            "distance_km": 3.35,
                        }
                    ],
                    "pharmacies": [
                        {
                            "name": "Station Night Pharmacy (mock)",
                            "location": {"name": "Bongbang-dong (mock)", "lat": 36.972, "lon": 127.897},
                            "open_until": "04:00",
                            "tel": "043-000-0711",
                            "fetched_at": _FETCHED,
                            "source": "MOCK",
                            "status": "LIVE",
                            "distance_km": 0.27,
                        }
                    ],
                    "otc": ["Sterile non-adherent dressing", "Saline solution"],
                    "notices": [],
                    "advice": "Get medical care soon: go to an ER or clinic.\n...\nNot medical advice. In an emergency call 119.",
                    "total_ms": 1120,
                }
            ]
        }
    )

    language: Language = Field(description="Language of the advice (detected or requested).")
    severity: Severity = Field(description="Triage level: red (critical), amber, green.")
    category: Category = Field(description="Detected emergency category.")
    call_119: bool = Field(description="True when the user should call 119 immediately.")
    location: Location = Field(description="Point distances are measured from.")
    location_source: LocationSource = Field(description="request (lat/lon), text (place named) or default.")
    at_time: str | None = Field(description="Local time used for pharmacy hours; null for critical cases.")
    er: list[ERFacility] = Field(default_factory=list, description="Up to 3 ERs, free beds first, then nearest.")
    pharmacies: list[PharmacyFacility] = Field(
        default_factory=list, description="Up to 3 pharmacies open at at_time, nearest first. Empty for critical."
    )
    otc: list[str] = Field(default_factory=list, description="Generic first-aid items. Empty for critical.")
    notices: list[Notice] = Field(default_factory=list, description="Warnings, e.g. ER_UNAVAILABLE, DATA_UNCERTAIN.")
    advice: str = Field(description="First-aid guidance in the user's language. Not medical advice.")
    total_ms: int = Field(ge=0, description="End-to-end latency in milliseconds (RT-105: <= 6000).")
