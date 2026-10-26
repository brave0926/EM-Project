"""API DTOs for the triage endpoint."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from backend.app.models.domain import ERFacility, PharmacyFacility
from backend.app.models.enums import Category, Language, Severity


class TriageRequestSchema(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [{"query": "Severe burn on my hand, near Chungju Station, 2 AM", "language": "en"}]
        }
    )

    query: str = Field(min_length=1, description="Free-text emergency description (EN/RU/ZH/KO).")
    language: Language | None = Field(
        default=None, description="Query language; auto-detected when omitted."
    )


class TriageResponseSchema(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "severity": "amber",
                    "category": "burn",
                    "er": [
                        {
                            "name": "Chungju Medical Center ER (mock)",
                            "location": {"name": "Anrim-dong (mock)", "lat": 36.981, "lon": 127.936},
                            "hvec": 5,
                            "tel": "043-000-0114",
                            "fetched_at": "2026-10-26T17:00:00Z",
                            "source": "MOCK",
                            "status": "LIVE",
                            "distance_km": 2.4,
                        }
                    ],
                    "pharmacies": [
                        {
                            "name": "Station Night Pharmacy (mock)",
                            "location": {"name": "Bongbang-dong (mock)", "lat": 36.972, "lon": 127.897},
                            "open_until": "04:00",
                            "tel": "043-000-0711",
                            "fetched_at": "2026-10-26T17:00:00Z",
                            "source": "MOCK",
                            "status": "LIVE",
                            "distance_km": 0.6,
                        }
                    ],
                    "advice": "Cool the burn under cool running water for 20 minutes. Not medical advice.",
                    "call_119": False,
                    "total_ms": 1840,
                }
            ]
        }
    )

    severity: Severity = Field(description="Triage level: red (critical), amber, green.")
    category: Category = Field(description="Detected emergency category.")
    er: list[ERFacility] = Field(
        default_factory=list, description="Nearby ERs, nearest first, with free beds (hvec)."
    )
    pharmacies: list[PharmacyFacility] = Field(
        default_factory=list, description="Nearby pharmacies open now, nearest first."
    )
    advice: str = Field(description="Streamed first-aid guidance. Not medical advice.")
    call_119: bool = Field(description="True when the user should call 119 immediately.")
    total_ms: int = Field(ge=0, description="End-to-end latency in milliseconds (RT-105: <= 6000).")
