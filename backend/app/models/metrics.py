"""Metrics (domain): one record per triage request and the /metrics summary.

Privacy: a record holds timings, severity, notices and data-source labels only. It never holds
the user's text, location, time of day, facility names or any key.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from backend.app.models.enums import Notice, Severity

RequestKind = Literal["triage", "stream"]
SourceLabel = Literal["MOCK", "LIVE", "CACHED"]


class MetricsRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: RequestKind
    at: datetime  # when the request finished (store clock)
    sources: list[SourceLabel]  # data behind the answer; empty when no facility came back
    ttft_ms: int | None = Field(default=None, ge=0)  # stream only: first event
    er_ms: int | None = Field(default=None, ge=0)  # ER tool call (None: not called, e.g. circuit open)
    pharmacy_ms: int | None = Field(default=None, ge=0)  # pharmacy tool call
    fallback_ms: int | None = Field(default=None, ge=0)  # from the failure to cached data served
    total_ms: int = Field(ge=0)
    severity: Severity | None  # None only if the run was cut before triage
    notices: list[Notice]
    timed_out: bool = False  # stream cut by the RT-105 cap
    rt101_ok: bool | None  # None: not a stream
    rt102_ok: bool | None  # None: no tool call was made
    rt103_ok: bool | None  # None: no fallback served
    rt105_ok: bool


class ContractStats(BaseModel):
    contract: str  # RT-101 ...
    metric: str  # ttft_ms, er_ms, pharmacy_ms, fallback_ms, total_ms
    limit_ms: int
    count: int = 0
    p50_ms: int = 0
    p95_ms: int = 0
    max_ms: int = 0
    ok_rate: float = 0.0  # share of samples within the limit; 0.0 when count is 0


class MetricsSummary(BaseModel):
    capacity: int  # ring buffer size
    window: int  # records currently kept (<= capacity); every count below is over this window
    requests_total: int  # since start, including records already dropped from the window
    oldest_at: datetime | None
    newest_at: datetime | None
    by_kind: dict[str, int]
    by_severity: dict[str, int]
    by_notice: dict[str, int]
    by_source: dict[str, int]  # source mix, e.g. "MOCK", "CACHED+LIVE", "NONE"
    fallback_served: int  # requests in the window answered (partly) from the cache
    fallback_served_total: int  # cache answers since start, also from /facilities/*
    contracts: list[ContractStats]
    breakers: dict[str, dict[str, Any]]
