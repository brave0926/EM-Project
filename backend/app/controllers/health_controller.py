from __future__ import annotations

from fastapi import APIRouter

from backend.app.schemas.health import HealthResponse
from backend.app.services import health_service

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(**await health_service.get_health())
