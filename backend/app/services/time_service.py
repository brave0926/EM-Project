"""Read a clock time ("2 AM", "02:00", "새벽 2시", "凌晨2点", "в 2 ночи") from free text.
Pure: no I/O, no FastAPI."""

from __future__ import annotations

import re

_HHMM = re.compile(r"(?<!\d)([01]?\d|2[0-3]):([0-5]\d)(?!\d)")
_EN = re.compile(r"(?<!\d)(1[0-2]|0?[1-9])\s*([ap])\.?\s?m\b")
_KO = re.compile(r"(새벽|오전|오후|밤|저녁|아침)?\s*(\d{1,2})\s*시(?!간)")  # "3시간" = 3 hours
_ZH = re.compile(r"(凌晨|早上|上午|中午|下午|晚上)?\s*(\d{1,2})\s*[点點]")
_RU = re.compile(r"(?<!\d)(\d{1,2})\s*(?:час(?:а|ов)?\s*)?(ночи|утра|дня|вечера)")

_AM = {"a", "새벽", "오전", "아침", "凌晨", "早上", "上午", "утра"}
_PM = {"p", "오후", "저녁", "下午", "дня", "вечера"}
_NIGHT = {"밤", "晚上", "ночи"}  # before 6 -> early morning, otherwise evening


def _to_24h(hour: int, marker: str | None) -> int | None:
    if not 0 <= hour <= 24:
        return None
    if marker in _AM:
        hour %= 12
    elif marker in _PM or (marker in _NIGHT and 6 <= hour < 12):
        hour = hour % 12 + 12
    elif marker in _NIGHT and hour == 12:
        hour = 0
    return hour % 24


def parse_time(text: str) -> str | None:
    """Return "HH:MM" (local time) if the text names a clock time, else None."""
    lowered = text.lower()
    if m := _HHMM.search(lowered):
        return f"{int(m[1]):02d}:{m[2]}"
    for pattern, hour_group, marker_group in ((_EN, 1, 2), (_KO, 2, 1), (_ZH, 2, 1), (_RU, 1, 2)):
        if m := pattern.search(lowered):
            hour = _to_24h(int(m[hour_group]), m[marker_group])
            if hour is not None:
                return f"{hour:02d}:00"
    return None
