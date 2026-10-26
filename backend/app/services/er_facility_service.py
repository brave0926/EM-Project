"""Use case: find ERs, free beds first. Pure: no FastAPI."""

from __future__ import annotations

from backend.app.clients.mcp_client import get_mcp_client
from backend.app.models.domain import ERFacility, Location


async def find_ers(
    region: str, lat: float | None = None, lon: float | None = None, available_only: bool = False
) -> list[ERFacility]:
    near = Location(name="user", lat=lat, lon=lon) if lat is not None and lon is not None else None
    ers = await get_mcp_client().get_er_beds(region, near=near)
    if available_only:
        ers = [e for e in ers if e.hvec > 0]
    # stable sort: keeps the provider's distance order within each group
    return sorted(ers, key=lambda e: e.hvec == 0)
