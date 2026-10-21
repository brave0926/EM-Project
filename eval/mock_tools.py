"""Mock ER and pharmacy tools with NMC-like fields. All data is labelled MOCK."""

from __future__ import annotations

import asyncio
import random
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel

DEFAULT_LATENCY = 0.8
DEFAULT_JITTER = 0.2

_rng = random.Random()


class ERBeds(BaseModel):
    name: str
    region: str
    hvec: int  # free ER beds (NMC field name)
    tel: str
    fetched_at: datetime
    source: Literal["MOCK"] = "MOCK"


class Pharmacy(BaseModel):
    name: str
    lat: float
    lon: float
    open_until: str  # "HH:MM", local time
    tel: str
    fetched_at: datetime
    source: Literal["MOCK"] = "MOCK"


_ERS = [
    ("Chungju Medical Center ER (mock)", 5, "043-000-0114"),
    ("Konkuk Univ. Chungju Hospital ER (mock)", 0, "043-000-0200"),
    ("Chungju Central ER (mock)", 2, "043-000-0300"),
]

_PHARMACIES = [
    ("Yeonsu Central Pharmacy (mock)", 36.954, 127.940, "06:00", "043-000-0845"),
    ("Station Night Pharmacy (mock)", 36.972, 127.897, "04:00", "043-000-0711"),
    ("Campus Pharmacy (mock)", 36.989, 127.927, "23:00", "043-000-0522"),
]


async def _sleep(latency: float, jitter: float, rng: random.Random | None) -> None:
    r = rng or _rng
    await asyncio.sleep(max(0.0, latency + r.uniform(-jitter, jitter)))


async def er_beds(
    region: str,
    latency: float = DEFAULT_LATENCY,
    jitter: float = DEFAULT_JITTER,
    rng: random.Random | None = None,
) -> list[ERBeds]:
    await _sleep(latency, jitter, rng)
    now = datetime.now(timezone.utc)
    return [ERBeds(name=n, region=region, hvec=b, tel=t, fetched_at=now) for n, b, t in _ERS]


async def pharmacy(
    lat: float,
    lon: float,
    latency: float = DEFAULT_LATENCY,
    jitter: float = DEFAULT_JITTER,
    rng: random.Random | None = None,
) -> list[Pharmacy]:
    await _sleep(latency, jitter, rng)
    now = datetime.now(timezone.utc)
    return [
        Pharmacy(name=n, lat=la, lon=lo, open_until=u, tel=t, fetched_at=now)
        for n, la, lo, u, t in _PHARMACIES
    ]
