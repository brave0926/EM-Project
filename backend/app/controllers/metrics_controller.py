from __future__ import annotations

from fastapi import APIRouter, Query

from backend.app.schemas.metrics import MetricsResponse
from backend.app.services import metrics_service

router = APIRouter()


@router.get("/metrics", response_model=MetricsResponse)
async def metrics(
    recent: int = Query(0, ge=0, le=50, description="Also return the last N request records."),
) -> MetricsResponse:
    """Latency per RT contract over the last requests (JSON). No user text or location is kept."""
    return MetricsResponse.model_validate(metrics_service.get_summary(recent).model_dump())
