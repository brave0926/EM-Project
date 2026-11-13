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
    MINOR = "minor"  # sore throat, runny nose: GREEN unless a severity or danger word lifts it
    # High-risk injuries: never GREEN, never product suggestions (minimal first-aid entries).
    HEAD_INJURY = "head_injury"  # AMBER
    EYE_INJURY = "eye_injury"  # AMBER
    BITE = "bite"  # AMBER; a snake bite is RED
    ALLERGY = "allergy"  # AMBER; swelling of lips/mouth/tongue/throat or anaphylaxis is RED
    FRACTURE = "fracture"  # AMBER (suspected broken bone, deformity)
    CHOKING = "choking"  # RED
    ELECTRIC_SHOCK = "electric_shock"  # RED
    DROWNING = "drowning"  # RED
    HEAVY_BLEEDING = "heavy_bleeding"  # RED (bleeding that does not stop)
    CRITICAL = "critical"
    OTHER = "other"


class Patient(StrEnum):
    """Who is hurt, read from the text: the writer (self), someone else (other) or not said (unknown).
    Only the wording of advice and first aid changes; severity never does."""

    SELF = "self"
    OTHER = "other"
    UNKNOWN = "unknown"


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
    FIRST_AID_UNAVAILABLE = "FIRST_AID_UNAVAILABLE"  # first-aid guide not loaded: the advice template stands


class LlmOutcome(StrEnum):
    """What happened to an LLM job. off: no LLM call was made (EM_LLM=off, no key, or not needed)."""

    OK = "ok"
    TIMEOUT = "timeout"
    INVALID = "invalid"
    ERROR = "error"
    OFF = "off"
