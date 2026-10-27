"""API DTOs for POST /api/triage/stream (Server-Sent Events)."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from pydantic import TypeAdapter

from backend.app.models.stream import StreamEvent
from backend.app.schemas.triage import TriageRequestSchema

SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}  # no proxy buffering (Nginx)
_EVENT = TypeAdapter(StreamEvent)


class TriageStreamRequestSchema(TriageRequestSchema):
    """Same body as POST /api/triage."""


def sse(event: StreamEvent) -> str:
    """One SSE message: `event: <name>` + one-line JSON `data:`."""
    data = json.dumps(_EVENT.dump_python(event, mode="json"), ensure_ascii=False)
    return f"event: {event.event}\ndata: {data}\n\n"


async def sse_stream(events: AsyncIterator[StreamEvent]) -> AsyncIterator[str]:
    async for event in events:
        yield sse(event)


EXAMPLE = (
    'event: triage\ndata: {"event": "triage", "severity": "red", "category": "critical", "call_119": true, '
    '"language": "en", "location": {"name": "Chungju Station (approx.)", "lat": 36.972, "lon": 127.9, '
    '"source": "text"}, "at_time": null, "prompt_119": "This may be life-threatening. Call 119 now.", "t_ms": 1}\n\n'
    'event: er\ndata: {"event": "er", "facilities": [{"name": "Chungju Medical Center ER (mock)", "hvec": 5, '
    '"status": "LIVE", "fetched_at": "2026-10-27T03:00:00Z", "distance_km": 3.35, "...": "..."}], "t_ms": 812}\n\n'
    'event: advice\ndata: {"event": "advice", "language": "en", "advice": "This may be life-threatening. '
    'Call 119 now.\\n...", "t_ms": 815}\n\n'
    'event: done\ndata: {"event": "done", "total_ms": 815, "stages": {"triage": 1, "er": 812, "advice": 815}, '
    '"notices": [], "timed_out": false, "rt101_ok": true, "rt105_ok": true}\n\n'
)

RESPONSES: dict[int | str, dict[str, Any]] = {
    200: {
        "description": (
            "text/event-stream. Each message is `event: <name>` + `data: <json>`. Order: `triage` first "
            "(rules only, RT-101 <= 1.5 s, with the 119 prompt for RED), then `er` and `pharmacy` as each "
            "worker finishes (either order; no pharmacy for RED), `notice` whenever a notice is known, "
            "`advice`, and `done` (timings, rt101_ok, rt105_ok) after which the stream closes. "
            "Capped at RT-105 (6 s): then `done` has rt105_ok=false. The `data` payloads follow the "
            "StreamEvent schema (discriminated by `event`)."
        ),
        "content": {"text/event-stream": {"schema": _EVENT.json_schema(), "example": EXAMPLE}},
    }
}
