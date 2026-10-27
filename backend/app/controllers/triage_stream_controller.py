from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from backend.app.graph.triage_graph import stream_updates
from backend.app.schemas.triage_stream import RESPONSES, SSE_HEADERS, TriageStreamRequestSchema, sse_stream
from backend.app.services import triage_stream_service

router = APIRouter()


@router.post("/api/triage/stream", response_class=StreamingResponse, responses=RESPONSES)
async def triage_stream(request: TriageStreamRequestSchema) -> StreamingResponse:
    """Triage as Server-Sent Events: severity first, then facilities as they arrive, then advice."""
    updates = stream_updates(request.query, request.language, request.lat, request.lon, request.at_time)
    events = triage_stream_service.stream_triage(updates)
    return StreamingResponse(sse_stream(events), media_type="text/event-stream", headers=SSE_HEADERS)
