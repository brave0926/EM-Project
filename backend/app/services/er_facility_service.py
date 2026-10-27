"""Use case: find ERs, free beds first. Pure: no FastAPI."""

from __future__ import annotations

from backend.app.clients.mcp_client import get_mcp_client
from backend.app.models.domain import ERFacility, Location
from backend.app.models.enums import Notice
from backend.app.services import fallback_service
from backend.app.services.geo import haversine_km


async def find_ers(
    region: str, lat: float | None = None, lon: float | None = None, available_only: bool = False
) -> tuple[list[ERFacility], list[Notice]]:
    """Returns (ERs, notices). Falls back to the last saved list for the region if the lookup fails."""
    near = Location(name="user", lat=lat, lon=lon) if lat is not None and lon is not None else None
    # Keyed by region only: the bed list is region-wide, distances are recomputed below.
    fetched = await fallback_service.fetch_or_fallback(
        "er", region.strip().lower(), lambda: get_mcp_client().get_er_beds(region, near=near), ERFacility
    )
    ers, notices = fetched.items, []
    if fetched.from_cache:
        ers = _with_distances(ers, near)
        notices.append(Notice.FALLBACK_CACHE)
    if available_only:
        ers = [e for e in ers if e.hvec > 0]
    # stable sort: keeps the distance order within each group
    return sorted(ers, key=lambda e: e.hvec == 0), notices


def _with_distances(ers: list[ERFacility], near: Location | None) -> list[ERFacility]:
    """Saved ERs re-measured from the current position, nearest first."""
    if near is None:
        return [e.model_copy(update={"distance_km": None}) for e in ers]
    ers = [
        e.model_copy(update={"distance_km": haversine_km(near.lat, near.lon, e.location.lat, e.location.lon)})
        for e in ers
    ]
    return sorted(ers, key=lambda e: e.distance_km)
