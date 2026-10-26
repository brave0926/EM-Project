from __future__ import annotations

from fastapi import APIRouter

from backend.app.graph.triage_graph import run_triage
from backend.app.schemas.triage import TriageRequestSchema, TriageResponseSchema

router = APIRouter()


@router.post("/api/triage", response_model=TriageResponseSchema)
async def triage(request: TriageRequestSchema) -> TriageResponseSchema:
    outcome = await run_triage(request.query, request.language, request.lat, request.lon, request.at_time)
    return TriageResponseSchema.model_validate(outcome.model_dump())
