"""Use case: find pharmacies open at a given local time. Pure: no FastAPI."""

from __future__ import annotations

from datetime import datetime

from backend.app.clients.mcp_client import get_mcp_client
from backend.app.core.config import KST
from backend.app.models.domain import Location, PharmacyFacility


async def find_open_pharmacies(
    lat: float, lon: float, at_time: str | None = None
) -> tuple[str, list[PharmacyFacility]]:
    """Returns (at_time actually used, pharmacies open then, nearest first)."""
    at_time = at_time or datetime.now(KST).strftime("%H:%M")
    near = Location(name="user", lat=lat, lon=lon)
    return at_time, await get_mcp_client().get_pharmacies(near, at_time=at_time)
