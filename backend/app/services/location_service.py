"""Where is the user? Request coordinates, else a known place named in the text, else the
city centre. Pure: no I/O, no FastAPI. Coordinates are approximate (mock area)."""

from __future__ import annotations

from backend.app.models.domain import Location, LocationSource

CITY_CENTRE = Location(name="Chungju City Hall (approx.)", lat=36.991, lon=127.926)

# (place, names to look for in EN/RU/ZH/KO, lower-case)
_PLACES: list[tuple[Location, list[str]]] = [
    (
        Location(name="Chungju Station (approx.)", lat=36.972, lon=127.900),
        ["chungju station", "вокзал чхунджу", "станция чхунджу", "忠州站", "충주역"],
    ),
    (
        Location(name="Yeonsu-dong (approx.)", lat=36.957, lon=127.938),
        ["yeonsu", "ёнсу", "연수동"],
    ),
    (CITY_CENTRE, ["city hall", "мэрия", "忠州市政府", "충주시청", "시청"]),
]


def resolve_location(text: str, lat: float | None = None, lon: float | None = None) -> tuple[Location, LocationSource]:
    if lat is not None and lon is not None:
        return Location(name="user", lat=lat, lon=lon), "request"
    lowered = text.lower()
    for place, names in _PLACES:
        if any(n in lowered for n in names):
            return place, "text"
    return CITY_CENTRE, "default"
