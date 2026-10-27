"""Use case: find pharmacies open at a given local time. Pure: no FastAPI."""

from __future__ import annotations

from datetime import datetime

from backend.app.clients.mcp_client import get_mcp_client
from backend.app.core.config import KST
from backend.app.models.domain import Location, PharmacyFacility
from backend.app.models.enums import Notice
from backend.app.services import fallback_service
from backend.app.services.geo import haversine_km


async def find_open_pharmacies(
    lat: float, lon: float, at_time: str | None = None
) -> tuple[str, list[PharmacyFacility], list[Notice]]:
    """Returns (at_time actually used, pharmacies open then nearest first, notices).
    Falls back to the last saved list near this point (about 1 km grid) if the lookup fails."""
    at_time = at_time or datetime.now(KST).strftime("%H:%M")
    near = Location(name="user", lat=lat, lon=lon)
    fetched = await fallback_service.fetch_or_fallback(
        "pharmacy",
        f"{lat:.2f},{lon:.2f}",
        lambda: get_mcp_client().get_pharmacies(near, at_time=at_time),
        PharmacyFacility,
        meta={"at_time": at_time},
    )
    if not fetched.from_cache:
        return at_time, fetched.items, []
    same_time = fetched.meta.get("at_time") == at_time
    pharmacies = [
        p.model_copy(
            update={
                "distance_km": haversine_km(lat, lon, p.location.lat, p.location.lon),
                # saved for another time: the source only had hours for that moment
                "is_open": p.is_open if same_time else None,
            }
        )
        for p in fetched.items
    ]
    return at_time, sorted(pharmacies, key=lambda p: p.distance_km), [Notice.FALLBACK_CACHE]
