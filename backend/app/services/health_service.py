"""Health use case. Pure: no I/O, no FastAPI."""

from __future__ import annotations

from backend.app.core.config import settings


async def get_health() -> dict[str, str]:
    return {"status": "ok", "version": settings.version}
