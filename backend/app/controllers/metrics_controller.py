from __future__ import annotations

from fastapi import APIRouter

from backend.app.schemas.metrics import MetricsResponse
from backend.app.services import metrics_service

router = APIRouter()


@router.get("/metrics", response_model=MetricsResponse)
async def metrics() -> MetricsResponse:
    """Latency per RT contract over the last requests (JSON). No user text or location is kept."""
    return MetricsResponse.model_validate(metrics_service.get_summary().model_dump())
