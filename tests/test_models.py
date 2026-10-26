from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from backend.app.models.domain import ERFacility, Location, PharmacyFacility
from backend.app.models.enums import Category, DataStatus, Language, Severity
from backend.app.schemas.triage import TriageResponseSchema
from backend.app.services.freshness import freshness_status
from backend.app.services.geo import haversine_km

NOW = datetime(2026, 10, 26, 12, 0, tzinfo=timezone.utc)
LOC = Location(name="Chungju (mock)", lat=36.991, lon=127.926)


def _er(**overrides) -> ERFacility:
    fields = dict(
        name="Chungju Medical Center ER (mock)",
        location=LOC,
        hvec=5,
        tel="043-000-0114",
        fetched_at=datetime.now(timezone.utc),
    )
    return ERFacility(**(fields | overrides))


def test_valid_response():
    pharm = PharmacyFacility(
        name="Campus Pharmacy (mock)",
        location=LOC,
        open_until="23:00",
        tel="043-000-0522",
        fetched_at=datetime.now(timezone.utc),
        distance_km=1.2,
    )
    resp = TriageResponseSchema(
        language=Language.EN,
        severity=Severity.AMBER,
        category=Category.BURN,
        location=LOC,
        location_source="text",
        at_time="02:00",
        er=[_er()],
        pharmacies=[pharm],
        advice="Cool the burn under running water.",
        call_119=False,
        total_ms=840,
    )
    assert resp.er[0].hvec == 5
    assert resp.er[0].source == "MOCK"
    assert resp.er[0].status is DataStatus.LIVE


def test_negative_hvec_rejected():
    with pytest.raises(ValidationError):
        _er(hvec=-1)


def test_uncertain_after_180_min():
    assert freshness_status(DataStatus.LIVE, NOW - timedelta(minutes=181), NOW) is DataStatus.UNCERTAIN
    assert freshness_status(DataStatus.LIVE, NOW - timedelta(minutes=179), NOW) is DataStatus.LIVE


def test_stale_facility_downgraded():
    stale = _er(fetched_at=datetime.now(timezone.utc) - timedelta(minutes=181))
    assert stale.status is DataStatus.UNCERTAIN
    fresh = _er(status=DataStatus.CACHED, fetched_at=datetime.now(timezone.utc) - timedelta(minutes=179))
    assert fresh.status is DataStatus.CACHED


def test_haversine_known_distance():
    assert haversine_km(36.0, 127.0, 36.009, 127.0) == pytest.approx(1.0, abs=0.01)
