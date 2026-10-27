"""Health use case. Pure: no I/O, no FastAPI."""

from __future__ import annotations

from typing import Any

from backend.app.core.config import settings
from backend.app.services import fallback_service


async def get_health() -> dict[str, Any]:
    return {"status": "ok", "version": settings.version, "breakers": fallback_service.breaker_status()}
