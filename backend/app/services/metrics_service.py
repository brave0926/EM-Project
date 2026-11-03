"""Use case: per-request metrics and the GET /metrics summary. No FastAPI, no I/O.

Records live in memory in a bounded ring buffer (last METRICS_CAPACITY requests), guarded by a
lock so threads and tasks can record at the same time. Percentiles are nearest-rank: the value at
rank ceil(p/100 * n) of the sorted samples, so every reported value was really measured.
Never stores the user's text, location or any key (see models/metrics.py).
"""

from __future__ import annotations

import math
import threading
from collections import Counter, deque
from collections.abc import Callable, Iterable, Sequence
from datetime import UTC, datetime

from backend.app.core.config import END_TO_END_S, FALLBACK_BUDGET_S, METRICS_CAPACITY, TOOL_TIMEOUT_S, TTFT_S
from backend.app.models.domain import ERFacility, PharmacyFacility
from backend.app.models.enums import DataStatus, Notice, Severity
from backend.app.models.metrics import ContractStats, MetricsRecord, MetricsSummary, RequestKind, SourceLabel
from backend.app.services import fallback_service, request_timing
from backend.app.services.request_timing import RequestTiming

TTFT_MS = round(TTFT_S * 1000)
TOOL_MS = round(TOOL_TIMEOUT_S * 1000)
FALLBACK_MS = round(FALLBACK_BUDGET_S * 1000)
TOTAL_MS = round(END_TO_END_S * 1000)


def _utc_now() -> datetime:
    return datetime.now(UTC)


class MetricsStore:
    def __init__(self, capacity: int = METRICS_CAPACITY, clock: Callable[[], datetime] = _utc_now) -> None:
        self.capacity = capacity
        self.clock = clock
        self._records: deque[MetricsRecord] = deque(maxlen=capacity)
        self._total = 0
        self._lock = threading.Lock()

    def add(self, record: MetricsRecord) -> None:
        with self._lock:
            self._records.append(record)
            self._total += 1

    def snapshot(self) -> tuple[list[MetricsRecord], int]:
        with self._lock:
            return list(self._records), self._total


_store = MetricsStore()


def get_store() -> MetricsStore:
    return _store


def set_store(store: MetricsStore | None) -> None:
    """Install a store (tests); None puts back a fresh default one."""
    global _store
    _store = store or MetricsStore()


def _sources(facilities: Iterable[ERFacility | PharmacyFacility], notices: Sequence[Notice]) -> list[SourceLabel]:
    labels: set[SourceLabel] = set()
    for f in facilities:
        labels.add(f.source)
        if f.status is DataStatus.CACHED:
            labels.add("CACHED")
    if Notice.FALLBACK_CACHE in notices:
        labels.add("CACHED")
    return sorted(labels)


def build_record(
    kind: RequestKind,
    timing: RequestTiming,
    *,
    total_ms: int,
    severity: Severity | None,
    notices: Sequence[Notice],
    facilities: Iterable[ERFacility | PharmacyFacility],
    ttft_ms: int | None = None,
    timed_out: bool = False,
    at: datetime,
) -> MetricsRecord:
    er_ms, pharmacy_ms = timing.tools.get("er"), timing.tools.get("pharmacy")
    tool_times = [t for t in (er_ms, pharmacy_ms) if t is not None]
    return MetricsRecord(
        kind=kind,
        at=at,
        sources=_sources(facilities, notices),
        ttft_ms=ttft_ms,
        er_ms=er_ms,
        pharmacy_ms=pharmacy_ms,
        fallback_ms=timing.fallback_ms,
        total_ms=total_ms,
        severity=severity,
        notices=list(dict.fromkeys(notices)),
        timed_out=timed_out,
        rt101_ok=None if ttft_ms is None else ttft_ms <= TTFT_MS,
        rt102_ok=all(t <= TOOL_MS for t in tool_times) if tool_times else None,
        rt103_ok=None if timing.fallback_ms is None else timing.fallback_ms <= FALLBACK_MS,
        rt105_ok=not timed_out and total_ms <= TOTAL_MS,
    )


def record(kind: RequestKind, timing: RequestTiming, **fields) -> MetricsRecord:
    """Build a record (see build_record) stamped with the store clock and keep it."""
    store = get_store()
    rec = build_record(kind, timing, at=store.clock(), **fields)
    store.add(rec)
    return rec


def percentile(values: Sequence[int], p: float) -> int:
    """Nearest-rank percentile; 0 for no values."""
    if not values:
        return 0
    ordered = sorted(values)
    rank = max(1, math.ceil(p / 100 * len(ordered)))
    return ordered[rank - 1]


def contract_stats(contract: str, metric: str, limit_ms: int, samples: Sequence[tuple[int, bool]]) -> ContractStats:
    """samples: (value_ms, within_limit). Empty -> zeros."""
    if not samples:
        return ContractStats(contract=contract, metric=metric, limit_ms=limit_ms)
    values = [v for v, _ in samples]
    return ContractStats(
        contract=contract,
        metric=metric,
        limit_ms=limit_ms,
        count=len(values),
        p50_ms=percentile(values, 50),
        p95_ms=percentile(values, 95),
        max_ms=max(values),
        ok_rate=round(sum(ok for _, ok in samples) / len(samples), 4),
    )


def _within(values: Iterable[int | None], limit_ms: int) -> list[tuple[int, bool]]:
    return [(v, v <= limit_ms) for v in values if v is not None]


def summarise(
    records: Sequence[MetricsRecord],
    *,
    capacity: int,
    requests_total: int,
    fallback_served_total: int,
    breakers: dict,
) -> MetricsSummary:
    """Pure: the summary of the given records."""
    sources = Counter("+".join(r.sources) or "NONE" for r in records)
    return MetricsSummary(
        capacity=capacity,
        window=len(records),
        requests_total=requests_total,
        oldest_at=min((r.at for r in records), default=None),
        newest_at=max((r.at for r in records), default=None),
        by_kind=dict(Counter(r.kind for r in records)),
        by_severity={s.value: sum(r.severity is s for r in records) for s in Severity},
        by_notice=dict(Counter(n.value for r in records for n in r.notices)),
        by_source=dict(sources),
        fallback_served=sum(r.fallback_ms is not None for r in records),
        fallback_served_total=fallback_served_total,
        contracts=[
            contract_stats("RT-101", "ttft_ms", TTFT_MS, _within((r.ttft_ms for r in records), TTFT_MS)),
            contract_stats("RT-102", "er_ms", TOOL_MS, _within((r.er_ms for r in records), TOOL_MS)),
            contract_stats("RT-102", "pharmacy_ms", TOOL_MS, _within((r.pharmacy_ms for r in records), TOOL_MS)),
            contract_stats("RT-103", "fallback_ms", FALLBACK_MS, _within((r.fallback_ms for r in records), FALLBACK_MS)),
            # RT-105 uses the record's flag: a stream cut at the cap fails even if total_ms <= 6000
            contract_stats("RT-105", "total_ms", TOTAL_MS, [(r.total_ms, r.rt105_ok) for r in records]),
        ],
        breakers=breakers,
    )


def get_summary() -> MetricsSummary:
    records, total = get_store().snapshot()
    return summarise(
        records,
        capacity=get_store().capacity,
        requests_total=total,
        fallback_served_total=request_timing.fallback_total(),
        breakers=fallback_service.breaker_status(),
    )
