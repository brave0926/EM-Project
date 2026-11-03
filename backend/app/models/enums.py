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


class Notice(StrEnum):
    """Warnings attached to a triage answer."""

    ER_UNAVAILABLE = "ER_UNAVAILABLE"
    PHARMACY_UNAVAILABLE = "PHARMACY_UNAVAILABLE"
    OTC_UNAVAILABLE = "OTC_UNAVAILABLE"
    NO_FREE_ER_BEDS = "NO_FREE_ER_BEDS"
    NO_OPEN_PHARMACY = "NO_OPEN_PHARMACY"
    DATA_UNCERTAIN = "DATA_UNCERTAIN"
    LOCATION_DEFAULT = "LOCATION_DEFAULT"
    FALLBACK_CACHE = "FALLBACK_CACHE"  # live lookup failed: last saved data shown
    NO_DATA = "NO_DATA"  # live lookup failed and nothing is saved
    LLM_FALLBACK = "LLM_FALLBACK"  # the LLM was expected but failed: rules/template used instead


class LlmOutcome(StrEnum):
    """What happened to an LLM job. off: no LLM call was made (EM_LLM=off, no key, or not needed)."""

    OK = "ok"
    TIMEOUT = "timeout"
    INVALID = "invalid"
    ERROR = "error"
    OFF = "off"
