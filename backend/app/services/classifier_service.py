"""Rule-based triage: category and severity from keywords in EN/RU/ZH/KO.

Cautious by design: critical signs -> red + 119; danger signs (bleeding, deep wound, poisoning...)
-> at least amber; anything unrecognised -> amber, never green.
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
    english: list[str]  # whole words/phrases, list each form ("bleed", "bleeding", "bleeds")
    russian: list[str]  # regex stems matched at a word start ("жар" must not match "пожар"); ё is read as е
    cjk: list[str]  # Chinese (simplified + traditional) / Korean substrings, matched with spaces removed


_KEYWORDS: dict[Category, Words] = {
    # RED + 119. Any match wins over every other category.
    Category.CRITICAL: Words(
        english=[
            "unconscious", "unresponsive", "not conscious", "passed out", "fainted", "collapsed",
            "not breathing", "can't breathe", "cannot breathe", "can not breathe", "stopped breathing",
            "hard to breathe", "difficulty breathing", "trouble breathing", "struggling to breathe",
            "short of breath", "shortness of breath", "chest pain", "chest pains", "chest tightness",
            "heart attack", "stroke", "seizure", "seizures", "seizing", "convulsion", "convulsions",
            "convulsing", "heavy bleeding", "severe bleeding", "bleeding heavily", "won't stop bleeding",
            "bleeding won't stop", "choking", "choked", "overdose", "overdosed", "no pulse",
            "anaphylaxis", "anaphylactic",
        ],
        russian=[
            r"без сознани", r"\w*теря\w* сознани", r"(?:упал\w*|падает) в обморок", r"обморок",
            r"не дыш", r"не мо\w* дышать", r"(?:трудно|тяжело|сложно|невозможно|не могу) дышать",
            r"одышк", r"задыха", r"удушь", r"бол\w* в груди", r"бол\w* груд", r"груд\w* бол", r"давит в груди",
            r"инфаркт", r"инсульт", r"судорог", r"судорож", r"припад\w*", r"эпилепс",
            r"(?:сильн|обильн|массивн)\w* кровотеч", r"кров\w* не останавл", r"нет пульса",
            r"анафилак", r"передозир", r"подавил",
        ],
        cjk=[
            # ZH
            "昏迷", "昏倒", "晕倒", "暈倒", "不省人事", "失去知觉", "失去知覺", "失去意识", "失去意識",
            "没有呼吸", "沒有呼吸", "不能呼吸", "无法呼吸", "無法呼吸", "停止呼吸", "呼吸困难", "呼吸困難",
            "喘不过气", "喘不過氣", "喘不上气", "透不过气", "胸痛", "胸口痛", "胸口疼", "胸闷", "胸悶",
            "心脏病发作", "心臟病發作", "心梗", "中风", "中風", "脑卒中", "抽搐", "癫痫", "癲癇",
            "痉挛", "痙攣", "大出血", "血流不止", "止不住血", "没有脉搏", "沒有脈搏", "噎住", "窒息",
            "服药过量", "服藥過量", "过敏性休克", "過敏性休克",
            # KO (matched without spaces: "호흡 곤란" == "호흡곤란")
            "의식이없", "의식없", "의식을잃", "정신을잃", "기절", "쓰러졌", "쓰러져",
            "숨을안", "숨을못", "숨을쉬지", "숨쉬기힘", "숨쉬기어려", "숨이차", "숨이막", "호흡이없",
            "호흡곤란", "가슴통증", "가슴이아", "가슴아파", "가슴이답답", "흉통", "심장마비", "심근경색",
            "뇌졸중", "중풍", "발작", "경련", "과다출혈", "피가멈추지", "피가안멈", "지혈이안", "맥박이없",
            "질식", "목에걸", "과다복용", "아나필락시스",
        ],
    ),
    Category.BURN: Words(
        english=["burn", "burns", "burned", "burnt", "scald", "scalded", "scalding"],
        russian=[r"ожог", r"ожёг", r"обж[её]г", r"обожгл", r"обожж", r"ошпар"],
        cjk=["烧伤", "燒傷", "烫伤", "燙傷", "烧到", "燒到", "烫到", "燙到", "灼伤", "灼傷",
             "화상", "데었", "데인", "뎄"],
    ),
    Category.CUT: Words(
        english=["cut", "cuts", "laceration", "wound", "wounded", "bleed", "bleeds", "bleeding", "knife", "stabbed"],
        russian=[r"порез", r"поранил", r"ран[аыуе]?\b", r"ранен", r"кровотеч", r"кровоточ", r"кровит", r"кровь"],
        cjk=[
            "割伤", "割傷", "切伤", "切傷", "划伤", "劃傷", "刀伤", "刀傷", "伤口", "傷口", "流血", "出血",
            "베였", "베인", "상처", "찢어", "찢어진", "출혈", "피가나", "피가많", "피나",
        ],
    ),
    Category.FEVER: Words(
        english=["fever", "feverish", "temperature", "high temperature"],
        russian=[r"температур", r"жар(?:ом|у)?\b", r"лихорад"],
        cjk=["发烧", "發燒", "发热", "發熱", "高烧", "高燒",
             "열이", "열나", "열과", "열도", "열은", "열을", "열에", "발열", "고열", "미열"],
    ),
}
# Checked in this order: the first category that matches wins.
_PRIORITY = [Category.CRITICAL, Category.BURN, Category.CUT, Category.FEVER]

# Lift burn/cut/fever to AMBER: severity words and danger signs (bleeding, deep wound, poisoning,
# fracture...). A danger sign never comes back GREEN; with no category it is OTHER (AMBER) anyway.
_SEVERE = Words(
    english=[
        "severe", "severely", "deep", "large", "big", "badly", "blister", "blisters", "a lot",
        "bleed", "bleeds", "bleeding", "blood", "poison", "poisoned", "poisoning", "swallowed",
        "fracture", "broken bone", "head injury", "stabbed",
    ],
    russian=[r"сильн", r"глубок", r"больш", r"волдыр", r"много", r"кров", r"отрав", r"проглот",
             r"перелом", r"травм\w* голов"],
    cjk=[
        "严重", "嚴重", "很深", "深度", "伤口深", "傷口深", "大面积", "大面積", "水泡", "很大", "大量",
        "出血", "流血", "血流", "中毒", "误服", "誤服", "骨折",
        "심한", "심하게", "깊", "크게", "넓", "물집", "많이", "출혈", "피가", "피나", "중독", "삼켰", "골절",
    ],
)
# A two-digit number, optionally with a decimal, not followed by a time/duration word
# ("40 minutes", "10 PM", "12시" are not temperatures).
_TEMPERATURE = re.compile(
    r"(?<![\d.,])(\d{2}(?:[.,]\d)?)(?![\d.,]?\d)"
    r"(?!\s*(?:min|hour|h\b|day|am\b|pm\b|мин|час|дн|분|시|일|分|小时|小時|天|点|點))"
)


def _normalise(text: str) -> tuple[str, str]:
    """(lower-case with ё -> е and ’ -> ', the same without whitespace for CJK matching)."""
    lowered = text.lower().replace("ё", "е").replace("\u2019", "'")
    return lowered, re.sub(r"\s+", "", lowered)


def _matches(text: str, words: Words) -> bool:
    lowered, compact = _normalise(text)
    return (
        any(re.search(rf"\b{re.escape(w)}\b", lowered) for w in words.english)
        or any(re.search(rf"\b{w.replace('ё', 'е')}", lowered) for w in words.russian)
        or any(w in compact for w in words.cjk)
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
