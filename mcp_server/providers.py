"""Data provider layer. MockProvider is the default; LiveProvider awaits a data.go.kr key.

All mock data is labelled MOCK. Freshness (RT-104) is applied by the models in backend/models.py.
"""

from __future__ import annotations

import asyncio
import os
import random
from abc import ABC, abstractmethod
from datetime import datetime, time, timedelta, timezone

from backend.models import Category, ERFacility, Location, PharmacyFacility, haversine_km

KST = timezone(timedelta(hours=9))


class ProviderError(Exception):
    """Raised when the upstream data source fails."""


class DataProvider(ABC):
    @abstractmethod
    async def get_er_beds(self, region: str, near: Location | None = None) -> list[ERFacility]: ...

    @abstractmethod
    async def get_pharmacies(
        self, near: Location, at_time: str | None = None
    ) -> list[PharmacyFacility]: ...

    @abstractmethod
    async def get_otc(self, category: Category) -> list[str]: ...


# name, area, lat, lon, hvec, tel
_ERS = [
    ("Chungju Medical Center ER (mock)", "Anrim-dong (mock)", 36.981, 127.936, 5, "043-000-0114"),
    ("Konkuk Univ. Chungju Hospital ER (mock)", "Gyohyeon-dong (mock)", 36.975, 127.930, 0, "043-000-0200"),
    ("Chungju Central ER (mock)", "Yeonsu-dong (mock)", 36.962, 127.945, 2, "043-000-0300"),
]

# name, area, lat, lon, open_from, open_until, tel
_PHARMACIES = [
    ("Yeonsu Central Pharmacy (mock)", "Yeonsu-dong (mock)", 36.954, 127.940, "09:00", "06:00", "043-000-0845"),
    ("Station Night Pharmacy (mock)", "Bongbang-dong (mock)", 36.972, 127.897, "18:00", "04:00", "043-000-0711"),
    ("Campus Pharmacy (mock)", "Danwol-dong (mock)", 36.989, 127.927, "09:00", "23:00", "043-000-0522"),
]

_OTC: dict[Category, list[str]] = {
    Category.BURN: ["Sterile non-adherent dressing", "Saline solution", "Burn gel (use as labelled)"],
    Category.CUT: ["Sterile dressing", "Saline solution", "Antiseptic solution", "Adhesive bandages"],
    Category.FEVER: ["Antipyretic / fever reducer (use as labelled)", "Oral rehydration salts", "Thermometer"],
    Category.CRITICAL: [],  # call 119, not a pharmacy
    Category.OTHER: ["Sterile dressing", "Saline solution", "Antiseptic solution"],
}


def _hhmm(value: str) -> time:
    return datetime.strptime(value, "%H:%M").time()


def is_open(at: time, open_from: time, open_until: time) -> bool:
    """True if `at` falls in [open_from, open_until), handling hours that cross midnight."""
    if open_from <= open_until:
        return open_from <= at < open_until
    return at >= open_from or at < open_until


class MockProvider(DataProvider):
    def __init__(
        self,
        delay_ms_range: tuple[int, int] = (500, 1100),
        failure_rate: float = 0.0,
        stale_minutes: int = 0,
        seed: int | None = None,
    ) -> None:
        lo, hi = delay_ms_range
        if not 0 <= lo <= hi:
            raise ValueError("delay_ms_range must satisfy 0 <= min <= max")
        if not 0.0 <= failure_rate <= 1.0:
            raise ValueError("failure_rate must be in [0, 1]")
        if stale_minutes < 0:
            raise ValueError("stale_minutes must be >= 0")
        self.delay_ms_range = delay_ms_range
        self.failure_rate = failure_rate
        self.stale_minutes = stale_minutes
        self._rng = random.Random(seed)

    async def _simulate_call(self) -> datetime:
        await asyncio.sleep(self._rng.uniform(*self.delay_ms_range) / 1000)
        if self._rng.random() < self.failure_rate:
            raise ProviderError("mock upstream failure (injected)")
        return datetime.now(timezone.utc) - timedelta(minutes=self.stale_minutes)

    async def get_er_beds(self, region: str, near: Location | None = None) -> list[ERFacility]:
        fetched_at = await self._simulate_call()
        ers = [
            ERFacility(
                name=name,
                location=Location(name=area, lat=lat, lon=lon),
                hvec=hvec,
                tel=tel,
                fetched_at=fetched_at,
                source="MOCK",
                distance_km=haversine_km(near.lat, near.lon, lat, lon) if near else None,
            )
            for name, area, lat, lon, hvec, tel in _ERS
        ]
        if near:
            ers.sort(key=lambda f: f.distance_km)
        return ers

    async def get_pharmacies(
        self, near: Location, at_time: str | None = None
    ) -> list[PharmacyFacility]:
        fetched_at = await self._simulate_call()
        at = _hhmm(at_time) if at_time else datetime.now(KST).time()
        pharmacies = [
            PharmacyFacility(
                name=name,
                location=Location(name=area, lat=lat, lon=lon),
                open_until=until,
                tel=tel,
                fetched_at=fetched_at,
                source="MOCK",
                distance_km=haversine_km(near.lat, near.lon, lat, lon),
            )
            for name, area, lat, lon, start, until, tel in _PHARMACIES
            if is_open(at, _hhmm(start), _hhmm(until))
        ]
        return sorted(pharmacies, key=lambda f: f.distance_km)

    async def get_otc(self, category: Category) -> list[str]:
        await self._simulate_call()
        return list(_OTC[category])


class LiveProvider(DataProvider):
    """Placeholder for the real NMC / data.go.kr integration."""

    async def get_er_beds(self, region: str, near: Location | None = None) -> list[ERFacility]:
        raise NotImplementedError("data.go.kr key not available")

    async def get_pharmacies(
        self, near: Location, at_time: str | None = None
    ) -> list[PharmacyFacility]:
        raise NotImplementedError("data.go.kr key not available")

    async def get_otc(self, category: Category) -> list[str]:
        raise NotImplementedError("data.go.kr key not available")


def get_provider() -> DataProvider:
    name = os.environ.get("EM_PROVIDER", "mock").strip().lower()
    if name == "mock":
        return MockProvider()
    if name == "live":
        return LiveProvider()
    raise ValueError(f"unknown EM_PROVIDER: {name!r}")
