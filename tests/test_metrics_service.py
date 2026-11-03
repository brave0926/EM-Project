"""metrics_service: percentiles, ring buffer, ok_rate, empty store, privacy (pure, offline)."""

import threading
from datetime import UTC, datetime

from backend.app.models.enums import Notice, Severity
from backend.app.models.metrics import MetricsRecord
from backend.app.services import metrics_service, request_timing
from backend.app.services.metrics_service import MetricsStore, percentile
from backend.app.services.request_timing import RequestTiming

T0 = datetime(2026, 11, 3, 10, 0, tzinfo=UTC)


def rec(total_ms=100, *, er_ms=None, fallback_ms=None, ttft_ms=None, timed_out=False, severity=Severity.AMBER,
        notices=()):
    timing = RequestTiming(tools={} if er_ms is None else {"er": er_ms}, fallback_ms=fallback_ms)
    return metrics_service.build_record(
        "stream" if ttft_ms is not None else "triage", timing, total_ms=total_ms, severity=severity,
        notices=list(notices), facilities=[], ttft_ms=ttft_ms, timed_out=timed_out, at=T0,
    )


def summary(records, total=None):
    return metrics_service.summarise(
        records, capacity=1000, requests_total=len(records) if total is None else total,
        fallback_served_total=0, breakers={},
    )


def stats(s, contract, metric):
    return next(c for c in s.contracts if c.contract == contract and c.metric == metric)


def test_percentile_nearest_rank():
    assert percentile([40, 15, 50, 35, 20], 50) == 35  # rank ceil(2.5) = 3
    assert percentile([40, 15, 50, 35, 20], 95) == 50  # rank ceil(4.75) = 5
    assert percentile(list(range(1, 101)), 95) == 95
    assert percentile(list(range(1, 101)), 50) == 50
    assert percentile([7], 50) == percentile([7], 95) == 7
    assert percentile([], 95) == 0


def test_ring_buffer_keeps_last_n():
    store = MetricsStore(capacity=3, clock=lambda: T0)
    for total in range(5):
        store.add(rec(total))
    records, total = store.snapshot()
    assert [r.total_ms for r in records] == [2, 3, 4] and total == 5
    assert summary(records, total).window == 3 and summary(records, total).requests_total == 5


def test_ok_rate_against_limits():
    records = [rec(er_ms=1999), rec(er_ms=2000), rec(er_ms=2001), rec(total_ms=5000, timed_out=True)]
    s = summary(records)
    er = stats(s, "RT-102", "er_ms")
    assert (er.count, er.ok_rate, er.max_ms, er.limit_ms) == (3, round(2 / 3, 4), 2001, 2000)
    total = stats(s, "RT-105", "total_ms")
    assert total.count == 4 and total.ok_rate == 0.75  # the cut stream fails even below 6000 ms
    assert stats(s, "RT-103", "fallback_ms").count == 0


def test_record_flags():
    r = rec(ttft_ms=1501, er_ms=500, fallback_ms=201, total_ms=6001)
    assert (r.rt101_ok, r.rt102_ok, r.rt103_ok, r.rt105_ok) == (False, True, False, False)
    r = rec()
    assert (r.rt101_ok, r.rt102_ok, r.rt103_ok, r.rt105_ok) == (None, None, None, True)


def test_empty_store_is_zeros():
    s = metrics_service.get_summary()
    assert s.window == s.requests_total == s.fallback_served == s.fallback_served_total == 0
    assert s.oldest_at is None and s.by_kind == {} and s.by_severity == {"red": 0, "amber": 0, "green": 0}
    assert len(s.contracts) == 5
    assert all((c.count, c.p50_ms, c.p95_ms, c.max_ms, c.ok_rate) == (0, 0, 0, 0, 0.0) for c in s.contracts)
    assert set(s.breakers) == {"er", "pharmacy"}


def test_counters():
    records = [rec(severity=Severity.RED, notices=[Notice.FALLBACK_CACHE], fallback_ms=3), rec(), rec()]
    s = summary(records)
    assert s.by_severity == {"red": 1, "amber": 2, "green": 0}
    assert s.by_notice == {"FALLBACK_CACHE": 1} and s.fallback_served == 1
    assert s.by_source == {"CACHED": 1, "NONE": 2}


def test_record_uses_store_clock():
    metrics_service.set_store(MetricsStore(clock=lambda: T0))
    metrics_service.record("triage", RequestTiming(), total_ms=5, severity=Severity.GREEN, notices=[], facilities=[])
    assert metrics_service.get_summary().newest_at == T0


def test_concurrent_adds_are_all_counted():
    store = MetricsStore(capacity=10_000)
    threads = [threading.Thread(target=lambda: [store.add(rec()) for _ in range(500)]) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    records, total = store.snapshot()
    assert len(records) == total == 4000


def test_record_has_no_user_text_or_location():
    fields = set(MetricsRecord.model_fields)
    assert not fields & {"query", "text", "location", "lat", "lon", "at_time", "advice", "facilities"}


def test_timing_notes_only_inside_track():
    request_timing.note_tool("er", 5)  # outside: ignored
    request_timing.note_fallback(9)  # outside: only the global counter
    with request_timing.track() as timing:
        request_timing.note_tool("er", 12)
        request_timing.note_fallback(4)
        request_timing.note_fallback(2)
    assert timing.tools == {"er": 12} and timing.fallback_ms == 4
    assert request_timing.fallback_total() == 3
