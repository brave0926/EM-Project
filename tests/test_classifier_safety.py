"""Safety invariants of the rule classifier and the place table, in EN/RU/ZH/KO (offline).

- The 16 demo chips (frontend/index.html): one severity per chip in every language, place found by text.
- Danger phrases never come back GREEN; critical phrases are RED with call_119.
"""

import json
import re
from pathlib import Path

import pytest

from backend.app.models.enums import Category, Severity
from backend.app.services.classifier_service import classify
from backend.app.services.location_service import CITY_CENTRE, STATION, YEONSU

ROOT = Path(__file__).resolve().parents[1]
LANGS = ("en", "ru", "zh", "ko")


def demo_chips() -> dict[str, list[str]]:
    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    chips = {}
    for lang in LANGS:
        block = re.search(rf"\b{lang}:\{{.*?chips:(\[[^\]]*\])", html, re.S)
        chips[lang] = json.loads(block.group(1))
    return chips


CHIPS = demo_chips()
# Per chip (same order in every language): expected severity and the place it names (None: no place).
EXPECTED = [(Severity.AMBER, STATION), (Severity.AMBER, YEONSU), (Severity.GREEN, CITY_CENTRE), (Severity.RED, STATION)]


def test_demo_chips_are_four_per_language():
    assert all(len(CHIPS[lang]) == len(EXPECTED) for lang in LANGS)


@pytest.mark.parametrize("index", range(len(EXPECTED)))
def test_demo_chip_has_one_severity_in_every_language(index):
    severities = {lang: classify(CHIPS[lang][index]).severity for lang in LANGS}
    assert set(severities.values()) == {EXPECTED[index][0]}, severities


DANGER = {  # never GREEN (AMBER or RED)
    "en": ["I'm bleeding", "my son swallowed bleach, poisoning", "deep wound on the leg", "severe burn on the arm",
           "small cut but bleeding a lot", "fever and he swallowed pills", "broken bone after a fall",
           "head injury, small cut"],
    "ru": ["У меня кровь идёт", "кровотечение из пальца", "глубокая рана на ноге", "сильный ожог руки",
           "отравление грибами", "ребёнок проглотил таблетки", "небольшой порез, но много крови", "перелом руки"],
    "zh": ["深度割伤出血", "伤口很深", "手在流血", "严重烧伤", "食物中毒", "孩子误服了药", "骨折了", "割伤大量出血"],
    "ko": ["피가 나요", "깊은 상처", "손에 출혈이 있어요", "심한 화상", "식중독이에요", "아이가 약을 삼켰어요",
           "다리 골절", "베였는데 피가 많이 나요"],
}
CRITICAL = {  # RED + 119
    "en": ["he is unconscious", "she is not breathing", "chest pain", "hard to breathe", "having a seizure",
           "bleeding heavily from the leg", "he collapsed", "shortness of breath"],
    "ru": ["Мама без сознания", "он потерял сознание", "она не дышит", "трудно дышать", "Боль в груди",
           "болит в груди", "у него судороги", "сильное кровотечение", "задыхается"],
    "zh": ["他昏迷了", "没有呼吸", "胸痛", "胸口疼", "呼吸困难", "喘不过气", "抽搐了", "大出血", "晕倒了"],
    "ko": ["아버지가 의식이 없어요", "숨을 못 쉬어요", "가슴 통증", "가슴이 아파요", "호흡 곤란", "호흡곤란",
           "경련을 해요", "피가 멈추지 않아요", "쓰러졌어요"],
}
UNCLEAR = ["", "   ", "hello", "help me", "помогите", "что-то не так", "救命", "不舒服", "도와주세요", "이상해요"]


@pytest.mark.parametrize(("lang", "text"), [(lang, t) for lang in LANGS for t in DANGER[lang]])
def test_danger_phrase_is_never_green(lang, text):
    assert classify(text).severity is not Severity.GREEN


def test_at_least_six_phrases_per_language():
    assert all(len(DANGER[lang]) >= 6 and len(CRITICAL[lang]) >= 6 for lang in LANGS)


@pytest.mark.parametrize(("lang", "text"), [(lang, t) for lang in LANGS for t in CRITICAL[lang]])
def test_critical_phrase_is_red_with_119(lang, text):
    result = classify(text)
    assert (result.category, result.severity, result.call_119) == (Category.CRITICAL, Severity.RED, True)


@pytest.mark.parametrize("text", UNCLEAR)
def test_unclear_text_is_amber(text):
    result = classify(text)
    assert (result.category, result.severity, result.call_119) == (Category.OTHER, Severity.AMBER, False)


@pytest.mark.parametrize("text", ["небольшой ожог", "小烫伤", "작은 화상", "small burn", "У ребёнка жаром 38"])
def test_minor_cases_can_still_be_green(text):
    assert classify(text).severity is Severity.GREEN  # the fix must not turn everything AMBER
