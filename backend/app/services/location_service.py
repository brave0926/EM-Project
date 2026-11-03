"""Where is the user? Request coordinates, else a known place named in the text, else the
city centre. Pure: no I/O, no FastAPI. Coordinates are approximate (mock area)."""

from __future__ import annotations

import re

from backend.app.models.domain import Location, LocationSource
from backend.app.models.llm import KnownPlace

CITY_CENTRE = Location(name="Chungju City Hall (approx.)", lat=36.991, lon=127.926)
STATION = Location(name="Chungju Station (approx.)", lat=36.972, lon=127.900)
YEONSU = Location(name="Yeonsu-dong (approx.)", lat=36.957, lon=127.938)

# (place, regex stems per language). Matched on the lower-cased text with ё read as е, and again
# with spaces removed, so "у вокзала", "в Енсу-доне", "市政府", "충주 역" all resolve.
_PLACES: list[tuple[Location, list[str]]] = [
    (STATION, [
        r"chungju station", r"train station",                   # EN
        r"вокзал", r"станци\w* чхунджу",                         # RU: вокзал/вокзала/вокзале...
        r"忠州站", r"火[车車]站",                                   # ZH
        r"충주역", r"기차역",                                      # KO
    ]),
    (YEONSU, [
        r"yeonsu",                                               # EN
        r"[её]нсу", r"йонсу",                                    # RU: Ёнсу-дон / Енсу-доне
        r"[莲蓮]水",                                              # ZH: 莲水洞 / 蓮水洞
        r"연수동",                                                # KO (not "연수": also "training")
    ]),
    (CITY_CENTRE, [
        r"city hall",                                            # EN
        r"мэри[яиюей]", r"ратуш",                                # RU: мэрия/мэрии/мэрию/мэрией
        r"市政府", r"市[厅廳]",                                     # ZH: with or without 忠州
        r"시청",                                                  # KO: 충주시청, 시청 근처
    ]),
]
# The ids the LLM may name (models/llm.KnownPlace): it never supplies coordinates itself.
KNOWN_PLACES: dict[KnownPlace, Location] = {
    "chungju_station": STATION,
    "yeonsu_dong": YEONSU,
    "city_hall": CITY_CENTRE,
}


def known_place(place: KnownPlace) -> Location:
    return KNOWN_PLACES[place]


def resolve_location(text: str, lat: float | None = None, lon: float | None = None) -> tuple[Location, LocationSource]:
    if lat is not None and lon is not None:
        return Location(name="user", lat=lat, lon=lon), "request"
    lowered = text.lower().replace("ё", "е")
    compact = re.sub(r"\s+", "", lowered)
    for place, patterns in _PLACES:
        if any(re.search(p, lowered) or re.search(p, compact) for p in patterns):
            return place, "text"
    return CITY_CENTRE, "default"
