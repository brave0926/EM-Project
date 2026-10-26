from __future__ import annotations

from fastapi import APIRouter

from backend.app.core.config import settings
from backend.app.schemas.health import HealthResponse

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status="ok", version=settings.version)
