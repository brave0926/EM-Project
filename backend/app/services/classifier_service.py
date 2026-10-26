"""Rule-based triage: category and severity from keywords in EN/RU/ZH/KO.

Cautious by design: critical signs -> red + 119; anything unrecognised -> amber, never green.
Keywords of all languages are checked, so mixed-language queries still work.
Pure: no I/O, no FastAPI. Not medical advice.
"""

from __future__ import annotations

import re
from typing import NamedTuple

from backend.app.models.domain import TriageResult
from backend.app.models.enums import Category, Severity

HIGH_FEVER_C = 39.5


class Words(NamedTuple):
    english: list[str]  # whole-word match
    russian: list[str]  # stems, matched at a word start ("жар" must not match "пожар")
    cjk: list[str]  # Chinese/Korean stems, substring match (words are not space-separated)


_KEYWORDS: dict[Category, Words] = {
    Category.CRITICAL: Words(
        english=[
            "unconscious", "not breathing", "can't breathe", "cannot breathe", "stopped breathing",
            "chest pain", "heart attack", "stroke", "seizure", "heavy bleeding", "severe bleeding",
            "bleeding heavily", "won't stop bleeding", "choking", "overdose", "passed out",
            "no pulse", "anaphylaxis", "anaphylactic",
        ],
        russian=[
            "без сознания", "потерял сознание", "потеряла сознание", "не дышит", "не может дышать",
            "боль в груди", "инфаркт", "инсульт", "судорог", "сильное кровотечение", "задыха",
            "нет пульса",
        ],
        cjk=[
            "昏迷", "不省人事", "没有呼吸", "沒有呼吸", "不能呼吸", "呼吸困难", "呼吸困難", "胸痛",
            "心脏病发作", "中风", "中風", "抽搐", "大出血", "失去知觉", "没有脉搏",
            "의식이 없", "의식 없", "의식을 잃", "숨을 안", "숨을 못", "숨을 쉬지", "호흡이 없",
            "호흡곤란", "가슴 통증", "가슴이 아", "흉통", "심장마비", "뇌졸중", "발작", "경련",
            "과다출혈", "피가 멈추지", "기절", "맥박이 없",
        ],
    ),
    Category.BURN: Words(
        english=["burn", "burns", "burned", "burnt", "scald", "scalded"],
        russian=["ожог", "обжег", "обжёг", "ошпар"],
        cjk=["烧伤", "燒傷", "烫伤", "燙傷", "烧到", "烫到", "화상", "데었", "데인"],
    ),
    Category.CUT: Words(
        english=["cut", "cuts", "laceration", "wound", "bleeding", "knife"],
        russian=["порез", "рана", "раны", "кровотеч"],
        cjk=[
            "割伤", "割傷", "切伤", "切傷", "伤口", "傷口", "流血",
            "베였", "베인", "상처", "찢어", "출혈", "피가 나", "피가 많",
        ],
    ),
    Category.FEVER: Words(
        english=["fever", "feverish", "temperature"],
        russian=["температур", "жар", "лихорад"],
        cjk=["发烧", "發燒", "发热", "發熱", "高烧", "高燒", "열이", "열나", "열 나", "발열", "고열"],
    ),
}
# Checked in this order: the first category that matches wins.
_PRIORITY = [Category.CRITICAL, Category.BURN, Category.CUT, Category.FEVER]

_SEVERE = Words(
    english=["severe", "severely", "deep", "large", "big", "badly", "blister", "blisters", "a lot"],
    russian=["сильн", "глубок", "больш", "волдыр"],
    cjk=[
        "严重", "嚴重", "很深", "大面积", "大面積", "水泡", "很大",
        "심한", "심하게", "깊", "크게", "넓", "물집", "많이",
    ],
)
# A two-digit number, optionally with a decimal, not followed by a time/duration word
# ("40 minutes", "10 PM", "12시" are not temperatures).
_TEMPERATURE = re.compile(
    r"(?<![\d.,])(\d{2}(?:[.,]\d)?)(?![\d.,]?\d)"
    r"(?!\s*(?:min|hour|h\b|day|am\b|pm\b|мин|час|дн|분|시|일|分|小时|小時|天|点|點))"
)


def _matches(text: str, words: Words) -> bool:
    return (
        any(re.search(rf"\b{re.escape(w)}\b", text) for w in words.english)
        or any(re.search(rf"\b{re.escape(w)}", text) for w in words.russian)
        or any(w in text for w in words.cjk)
    )


def max_temperature_c(text: str) -> float | None:
    temps = [float(t.replace(",", ".")) for t in _TEMPERATURE.findall(text)]
    temps = [t for t in temps if 34.0 <= t <= 44.0]  # plausible body temperatures only
    return max(temps, default=None)


def classify(text: str) -> TriageResult:
    lowered = text.lower()
    category = next((c for c in _PRIORITY if _matches(lowered, _KEYWORDS[c])), Category.OTHER)
    if category is Category.CRITICAL:
        return TriageResult(category=category, severity=Severity.RED, call_119=True)
    if category is Category.OTHER:
        return TriageResult(category=category, severity=Severity.AMBER, call_119=False)
    temp = max_temperature_c(lowered) if category is Category.FEVER else None
    severe = _matches(lowered, _SEVERE) or (temp is not None and temp >= HIGH_FEVER_C)
    return TriageResult(category=category, severity=Severity.AMBER if severe else Severity.GREEN, call_119=False)
