"""Data provider layer. MockProvider is the default (EM_PROVIDER=mock); LiveProvider reads data.go.kr.

Mock data is labelled MOCK, live data LIVE (see docs/data_sources.md). Freshness (RT-104) is applied by the domain models in backend/app/models/domain.py.
"""

from __future__ import annotations

import asyncio
import os
import random
import xml.etree.ElementTree as ET
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from datetime import datetime, time, timedelta, timezone
from time import monotonic
from typing import TypeVar
from urllib.parse import quote, quote_plus, unquote

import httpx

from backend.app.models.domain import ERFacility, Location, PharmacyFacility
from backend.app.models.enums import Category, DataStatus
from backend.app.services.geo import haversine_km

KST = timezone(timedelta(hours=9))
T = TypeVar("T")


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


CLOSED_SHOWN = 3  # nearest closed pharmacies listed when none is known to be open


def with_closed_fallback(
    listed: list[PharmacyFacility], closed: list[PharmacyFacility]
) -> list[PharmacyFacility]:
    """Open and unknown-hours pharmacies, nearest first. If none is known to be open, the nearest
    closed ones are added (is_open=False, open_until = closing time) so the user still sees options."""
    if not any(p.is_open for p in listed):
        listed = listed + sorted(closed, key=lambda p: p.distance_km)[:CLOSED_SHOWN]
    return sorted(listed, key=lambda p: p.distance_km)


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
                is_open=is_open(at, _hhmm(start), _hhmm(until)),
                tel=tel,
                fetched_at=fetched_at,
                source="MOCK",
                distance_km=haversine_km(near.lat, near.lon, lat, lon),
            )
            for name, area, lat, lon, start, until, tel in _PHARMACIES
        ]
        return with_closed_fallback([p for p in pharmacies if p.is_open], [p for p in pharmacies if not p.is_open])

    async def get_otc(self, category: Category) -> list[str]:
        await self._simulate_call()
        return list(_OTC[category])


_ER_URL = "https://apis.data.go.kr/B552657/ErmctInfoInqireService"
_PH_URL = "https://apis.data.go.kr/B552657/ErmctInsttInfoInqireService"
CALL_TIMEOUT_S = 1.5  # one upstream HTTP call
TOOL_BUDGET_S = 1.8  # whole tool call; leaves headroom under RT-102 (2.0 s) for MCP overhead
BEDS_TTL_S = 60.0
BASIC_TTL_S = 24 * 3600.0  # coordinates and address barely change; saves the 1000/day quota
NUM_OF_ROWS = "30"
DEFAULT_STAGES = ("충청북도", "충주시")
_REGIONS = {"chungju": DEFAULT_STAGES, "충주": DEFAULT_STAGES, "충주시": DEFAULT_STAGES}


def _read_key(name: str) -> str:
    key = os.environ.get(name, "").strip()
    return unquote(key) if "%" in key else key  # an already-encoded key would be encoded twice


def region_stages(region: str) -> tuple[str, str]:
    """Region -> (STAGE1, STAGE2). Accepts a known alias or "충청북도 충주시"."""
    region = region.strip()
    if not region:
        return DEFAULT_STAGES
    if stages := _REGIONS.get(region.lower()):
        return stages
    parts = region.split()
    if len(parts) == 2:
        return parts[0], parts[1]
    raise ProviderError(f"UNKNOWN_REGION: {region!r}")


def _text(item: ET.Element, *tags: str) -> str | None:
    """First non-empty tag value; None when all are absent (absent tags are normal)."""
    for tag in tags:
        value = (item.findtext(tag) or "").strip()
        if value:
            return value
    return None


def _int(item: ET.Element, tag: str) -> int | None:
    try:
        return int(_text(item, tag) or "")
    except ValueError:
        return None


def _float(item: ET.Element, tag: str) -> float | None:
    try:
        return float(_text(item, tag) or "")
    except ValueError:
        return None


def parse_hvidate(value: str | None) -> datetime | None:
    """NMC hvidate YYYYMMDDHHMMSS (KST, no zone in the string) -> aware datetime."""
    try:
        return datetime.strptime(value or "", "%Y%m%d%H%M%S").replace(tzinfo=KST)
    except ValueError:
        return None


def parse_nmc_hhmm(value: str | None) -> time | None:
    """NMC HHMM, where 2400 and later mean past midnight (2600 -> 02:00)."""
    if not value or len(value) != 4 or not value.isdigit() or int(value[2:]) > 59:
        return None
    return time(int(value[:2]) % 24, int(value[2:]))


def open_status(at: time, start: time | None, end: time | None) -> bool | None:
    if start is None or end is None:
        return None
    if start == end:  # 0000-2400: open all day
        return True
    return is_open(at, start, end)


def _items(root: ET.Element) -> list[ET.Element]:
    return root.findall("./body/items/item")


class LiveProvider(DataProvider):
    """data.go.kr (NMC) integration. Facility data is labelled LIVE; OTC lists are static."""

    def __init__(
        self,
        er_key: str | None = None,
        pharmacy_key: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        self._er_key = _read_key("EM_DATA_GO_KR_KEY") if er_key is None else er_key
        ph = _read_key("EM_DATA_GO_KR_KEY_PHARMACY") if pharmacy_key is None else pharmacy_key
        self._ph_key = ph or self._er_key
        self._transport = transport
        self._clock = clock
        self._client: httpx.AsyncClient | None = None
        self._beds: dict[tuple[str, str], tuple[float, list[ET.Element]]] = {}
        self._basic: dict[str, tuple[float, ET.Element | None]] = {}

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=CALL_TIMEOUT_S, transport=self._transport)
        return self._client

    async def _call(self, url: str, key: str, params: dict[str, str]) -> list[ET.Element]:
        """One upstream call -> items. Errors carry a code and message only, never the URL or key."""
        if not key:
            raise ProviderError("NO_KEY: data.go.kr service key is not set")
        op = url.rsplit("/", 1)[-1]
        try:
            resp = await self._http().get(url, params={"serviceKey": key, **params})
        except httpx.TimeoutException:
            raise ProviderError(f"UPSTREAM_TIMEOUT: {op}") from None
        except httpx.HTTPError as exc:
            raise ProviderError(f"UPSTREAM_UNAVAILABLE: {op} {type(exc).__name__}") from None
        if resp.status_code != 200:
            raise ProviderError(f"UPSTREAM_HTTP_{resp.status_code}: {op}")
        try:
            root = ET.fromstring(resp.text)
        except ET.ParseError:
            raise ProviderError(f"BAD_RESPONSE: {op} returned non-XML") from None
        if root.tag == "OpenAPI_ServiceResponse":  # gateway error: key, quota, unknown operation
            code = root.findtext(".//returnReasonCode") or "?"
            msg = root.findtext(".//returnAuthMsg") or root.findtext(".//errMsg") or "?"
        else:
            code = root.findtext("./header/resultCode") or "?"
            msg = root.findtext("./header/resultMsg") or "?"
        if code != "00":
            raise ProviderError(f"UPSTREAM_RESULT_{code}: {op} {self._redact(msg)}")
        return _items(root)

    def _redact(self, text: str) -> str:
        for key in {self._er_key, self._ph_key} - {""}:
            for form in (key, quote(key, safe=""), quote_plus(key)):
                text = text.replace(form, "***")
        return text

    async def _within_budget(self, call: Awaitable[T]) -> T:
        try:
            async with asyncio.timeout(TOOL_BUDGET_S):
                return await call
        except TimeoutError:
            raise ProviderError(f"UPSTREAM_TIMEOUT: over the {TOOL_BUDGET_S:.1f} s tool budget") from None

    async def _bed_items(self, stages: tuple[str, str]) -> list[ET.Element]:
        if (cached := self._beds.get(stages)) is not None and self._clock() - cached[0] < BEDS_TTL_S:
            return cached[1]
        items = await self._call(
            f"{_ER_URL}/getEmrrmRltmUsefulSckbdInfoInqire",
            self._er_key,
            {"STAGE1": stages[0], "STAGE2": stages[1], "pageNo": "1", "numOfRows": NUM_OF_ROWS},
        )
        self._beds[stages] = (self._clock(), items)
        return items

    async def _basic_item(self, hpid: str) -> ET.Element | None:
        if (cached := self._basic.get(hpid)) is not None and self._clock() - cached[0] < BASIC_TTL_S:
            return cached[1]
        items = await self._call(f"{_ER_URL}/getEgytBassInfoInqire", self._er_key, {"HPID": hpid})
        item = items[0] if items else None
        self._basic[hpid] = (self._clock(), item)
        return item

    async def get_er_beds(self, region: str, near: Location | None = None) -> list[ERFacility]:
        return await self._within_budget(self._er_beds(region_stages(region), near))

    async def _er_beds(self, stages: tuple[str, str], near: Location | None) -> list[ERFacility]:
        beds = {}
        for item in await self._bed_items(stages):
            hpid, hvec = _text(item, "hpid"), _int(item, "hvec")
            if hpid and hvec is not None:  # no hvec: no bed data, skip
                beds[hpid] = item
        basics = await asyncio.gather(*(self._basic_item(hpid) for hpid in beds))
        now = datetime.now(timezone.utc)
        ers = []
        for (hpid, bed), basic in zip(beds.items(), basics):
            if basic is None or (lat := _float(basic, "wgs84Lat")) is None or (lon := _float(basic, "wgs84Lon")) is None:
                continue  # no coordinates: cannot place it on a map
            name = _text(bed, "dutyName") or _text(basic, "dutyName") or hpid
            updated_at = parse_hvidate(_text(bed, "hvidate"))
            ers.append(
                ERFacility(
                    name=name,
                    location=Location(name=_text(basic, "dutyAddr") or name, lat=lat, lon=lon),
                    hvec=max(0, _int(bed, "hvec") or 0),  # negative hvec (overcrowded) -> 0 free
                    hvicc=None if (icc := _int(bed, "hvicc")) is None else max(0, icc),
                    tel=_text(bed, "dutyTel3", "dutyTel1") or _text(basic, "dutyTel1") or "",
                    fetched_at=updated_at or now,
                    source="LIVE",
                    # no hvidate: the age of the bed count is unknown
                    status=DataStatus.LIVE if updated_at else DataStatus.UNCERTAIN,
                    distance_km=haversine_km(near.lat, near.lon, lat, lon) if near else None,
                )
            )
        if near:
            ers.sort(key=lambda f: f.distance_km)
        return ers

    async def get_pharmacies(
        self, near: Location, at_time: str | None = None
    ) -> list[PharmacyFacility]:
        return await self._within_budget(self._pharmacies(near, at_time))

    async def _pharmacies(self, near: Location, at_time: str | None) -> list[PharmacyFacility]:
        items = await self._call(
            f"{_PH_URL}/getParmacyLcinfoInqire",
            self._ph_key,
            {"WGS84_LON": f"{near.lon}", "WGS84_LAT": f"{near.lat}", "pageNo": "1", "numOfRows": NUM_OF_ROWS},
        )
        fetched_at = datetime.now(timezone.utc)
        # at_time is a time of day, read as today in KST: the radius response only has today's hours
        at = _hhmm(at_time) if at_time else datetime.now(KST).time()
        pharmacies, closed = [], []
        for item in items:
            lat, lon = _float(item, "latitude"), _float(item, "longitude")
            if lat is None or lon is None:
                continue
            start, end = parse_nmc_hhmm(_text(item, "startTime")), parse_nmc_hhmm(_text(item, "endTime"))
            status = open_status(at, start, end)
            name = _text(item, "dutyName") or _text(item, "hpid") or "unknown pharmacy"
            distance = _float(item, "distance")
            (closed if status is False else pharmacies).append(
                PharmacyFacility(
                    name=name,
                    location=Location(name=_text(item, "dutyAddr") or name, lat=lat, lon=lon),
                    open_until=end.strftime("%H:%M") if end is not None and status is not None else None,
                    is_open=status,
                    tel=_text(item, "dutyTel1") or "",
                    fetched_at=fetched_at,
                    source="LIVE",
                    distance_km=distance if distance is not None and distance >= 0
                    else haversine_km(near.lat, near.lon, lat, lon),
                )
            )
        return with_closed_fallback(pharmacies, closed)

    async def get_otc(self, category: Category) -> list[str]:
        return list(_OTC[category])  # no data.go.kr source: static generic first-aid lists


def get_provider() -> DataProvider:
    name = os.environ.get("EM_PROVIDER", "mock").strip().lower()
    if name == "mock":
        return MockProvider()
    if name == "live":
        return LiveProvider()
    raise ValueError(f"unknown EM_PROVIDER: {name!r}")
