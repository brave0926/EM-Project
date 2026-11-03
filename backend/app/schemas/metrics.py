from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from backend.app.models.enums import Notice, Severity
from backend.app.schemas.health import BreakerStatus


class ContractStatsSchema(BaseModel):
    contract: str = Field(description="RT-101 (ttft), RT-102 (tool call), RT-103 (fallback), RT-105 (total).")
    metric: str = Field(description="ttft_ms, er_ms, pharmacy_ms, fallback_ms or total_ms.")
    limit_ms: int = Field(description="Contract limit from core/config.py.")
    count: int = Field(ge=0, description="Samples in the window.")
    p50_ms: int = Field(ge=0, description="Nearest-rank median; 0 when count is 0.")
    p95_ms: int = Field(ge=0, description="Nearest-rank 95th percentile; 0 when count is 0.")
    max_ms: int = Field(ge=0)
    ok_rate: float = Field(ge=0, le=1, description="Share of samples within the limit; 0 when count is 0.")


class MetricsRecordSchema(BaseModel):
    """One request: timings and labels only, never the user's text, location or a key."""

    kind: str = Field(description="triage or stream.")
    at: datetime
    sources: list[str] = Field(description="MOCK, LIVE, CACHED behind the answer.")
    ttft_ms: int | None
    er_ms: int | None = Field(description="ER tool call; null when skipped (circuit open).")
    pharmacy_ms: int | None
    fallback_ms: int | None = Field(description="From the failure to cached data served (RT-103).")
    total_ms: int
    severity: Severity | None
    notices: list[Notice]
    timed_out: bool
    chaos_active: bool
    rt101_ok: bool | None
    rt102_ok: bool | None
    rt103_ok: bool | None
    rt105_ok: bool


class MetricsResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "capacity": 1000,
                    "window": 2,
                    "requests_total": 2,
                    "oldest_at": "2026-11-03T10:00:00Z",
                    "newest_at": "2026-11-03T10:00:05Z",
                    "by_kind": {"stream": 2},
                    "by_severity": {"red": 1, "amber": 1, "green": 0},
                    "by_notice": {"FALLBACK_CACHE": 1},
                    "by_source": {"MOCK": 1, "CACHED+LIVE": 1},
                    "fallback_served": 1,
                    "fallback_served_total": 1,
                    "by_chaos": {"on": 1, "off": 1},
                    "contracts": [
                        {"contract": "RT-101", "metric": "ttft_ms", "limit_ms": 1500, "count": 2,
                         "p50_ms": 3, "p95_ms": 4, "max_ms": 4, "ok_rate": 1.0},
                        {"contract": "RT-102", "metric": "er_ms", "limit_ms": 2000, "count": 2,
                         "p50_ms": 640, "p95_ms": 2001, "max_ms": 2001, "ok_rate": 0.5},
                        {"contract": "RT-102", "metric": "pharmacy_ms", "limit_ms": 2000, "count": 1,
                         "p50_ms": 820, "p95_ms": 820, "max_ms": 820, "ok_rate": 1.0},
                        {"contract": "RT-103", "metric": "fallback_ms", "limit_ms": 200, "count": 1,
                         "p50_ms": 2, "p95_ms": 2, "max_ms": 2, "ok_rate": 1.0},
                        {"contract": "RT-105", "metric": "total_ms", "limit_ms": 6000, "count": 2,
                         "p50_ms": 900, "p95_ms": 2010, "max_ms": 2010, "ok_rate": 1.0},
                    ],
                    "breakers": {
                        "er": {"state": "CLOSED", "failures": 1, "last_error": "TIMEOUT"},
                        "pharmacy": {"state": "CLOSED", "failures": 0, "last_error": None},
                    },
                    "recent": [],
                }
            ]
        }
    )

    capacity: int = Field(description="Ring buffer size (last N requests kept in memory).")
    window: int = Field(ge=0, description="Requests in the window; every count below is over the window.")
    requests_total: int = Field(ge=0, description="Requests recorded since start.")
    oldest_at: datetime | None = Field(description="Oldest record in the window; null when empty.")
    newest_at: datetime | None = Field(description="Newest record in the window; null when empty.")
    by_kind: dict[str, int] = Field(description="triage (POST /api/triage) and stream (POST /api/triage/stream).")
    by_severity: dict[str, int] = Field(description="Requests per severity (red, amber, green).")
    by_notice: dict[str, int] = Field(description="Requests carrying each notice.")
    by_source: dict[str, int] = Field(description="Data source mix per request: MOCK, LIVE, CACHED, or NONE.")
    fallback_served: int = Field(ge=0, description="Requests in the window answered (partly) from the cache.")
    fallback_served_total: int = Field(ge=0, description="Cache answers since start, also from /facilities/*.")
    contracts: list[ContractStatsSchema] = Field(description="Per contract: count, p50, p95, max, ok_rate.")
    by_chaos: dict[str, int] = Field(description="Requests made while /demo/chaos was on / off.")
    breakers: dict[str, BreakerStatus] = Field(description="Circuit breaker per tool (er, pharmacy).")
    recent: list[MetricsRecordSchema] = Field(
        default_factory=list, description="Last N records, newest last; only with ?recent=N (max 50)."
    )
