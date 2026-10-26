"""Domain enums. Leaf module: imports nothing from the app."""

from __future__ import annotations

from enum import StrEnum


class Severity(StrEnum):
    RED = "red"
    AMBER = "amber"
    GREEN = "green"


class Category(StrEnum):
    BURN = "burn"
    CUT = "cut"
    FEVER = "fever"
    CRITICAL = "critical"
    OTHER = "other"


class DataStatus(StrEnum):
    LIVE = "LIVE"
    CACHED = "CACHED"
    UNCERTAIN = "UNCERTAIN"


class Language(StrEnum):
    EN = "en"
    RU = "ru"
    ZH = "zh"
    KO = "ko"
