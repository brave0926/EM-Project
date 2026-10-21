import asyncio
import time
from datetime import datetime

import pytest
from pydantic import ValidationError

from eval.mock_tools import DEFAULT_JITTER, DEFAULT_LATENCY, ERBeds, Pharmacy, er_beds, pharmacy

TOLERANCE = 0.1  # event-loop scheduling slack


async def _timed(coro):
    t0 = time.perf_counter()
    result = await coro
    return result, time.perf_counter() - t0


@pytest.mark.asyncio
async def test_default_delay_in_range():
    (_, er_t), (_, ph_t) = await asyncio.gather(
        _timed(er_beds("Chungju")), _timed(pharmacy(36.971, 127.899))
    )
    lo, hi = DEFAULT_LATENCY - DEFAULT_JITTER, DEFAULT_LATENCY + DEFAULT_JITTER
    for elapsed in (er_t, ph_t):
        assert lo - 0.01 <= elapsed <= hi + TOLERANCE


@pytest.mark.asyncio
async def test_er_beds_fields_and_source():
    rows = await er_beds("Chungju", latency=0, jitter=0)
    assert rows
    for r in rows:
        assert isinstance(r, ERBeds)
        assert set(r.model_dump()) == {"name", "region", "hvec", "tel", "fetched_at", "source"}
        assert r.source == "MOCK"
        assert r.region == "Chungju"
        assert isinstance(r.hvec, int) and r.hvec >= 0
        assert isinstance(r.fetched_at, datetime) and r.fetched_at.tzinfo is not None


@pytest.mark.asyncio
async def test_pharmacy_fields_and_source():
    rows = await pharmacy(36.971, 127.899, latency=0, jitter=0)
    assert rows
    for r in rows:
        assert isinstance(r, Pharmacy)
        assert set(r.model_dump()) == {"name", "lat", "lon", "open_until", "tel", "fetched_at", "source"}
        assert r.source == "MOCK"
        assert len(r.open_until) == 5 and r.open_until[2] == ":"
        assert isinstance(r.fetched_at, datetime) and r.fetched_at.tzinfo is not None


def test_source_must_be_mock():
    with pytest.raises(ValidationError):
        ERBeds(name="x", region="y", hvec=1, tel="0", fetched_at=datetime.now(), source="LIVE")
