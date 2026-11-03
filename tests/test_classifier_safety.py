"""Safety invariants of the rule classifier and the place table, in EN/RU/ZH/KO (offline).

- The 20 demo chips (frontend/index.html): one severity per chip in every language, place found by text.
- Danger phrases never come back GREEN; critical phrases are RED with call_119.
"""

import json
import re
from pathlib import Path

import pytest

from backend.app.models.enums import Category, Severity
from backend.app.services.classifier_service import classify
from backend.app.services.location_service import CITY_CENTRE, STATION, YEONSU, resolve_location

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
EXPECTED = [(Severity.AMBER, STATION), (Severity.AMBER, YEONSU), (Severity.AMBER, CITY_CENTRE), (Severity.RED, STATION),
            (Severity.GREEN, STATION)]


def test_demo_chips_are_five_per_language():
    assert all(len(CHIPS[lang]) == len(EXPECTED) for lang in LANGS)


@pytest.mark.parametrize("index", range(len(EXPECTED)))
def test_demo_chip_has_one_severity_in_every_language(index):
    severities = {lang: classify(CHIPS[lang][index]).severity for lang in LANGS}
    assert set(severities.values()) == {EXPECTED[index][0]}, severities


@pytest.mark.parametrize(("lang", "index"), [(lang, i) for lang in LANGS for i in range(len(EXPECTED))])
def test_demo_chip_place_is_found_by_text(lang, index):
    location, source = resolve_location(CHIPS[lang][index])
    assert (location, source) == (EXPECTED[index][1], "text")


@pytest.mark.parametrize(("text", "place"), [
    ("у вокзала Чхунджу", STATION), ("на вокзале", STATION), ("у мэрии", CITY_CENTRE), ("возле мэрии", CITY_CENTRE),
    ("в Ёнсу-доне", YEONSU), ("в Енсу-доне", YEONSU), ("莲水洞", YEONSU), ("蓮水洞附近", YEONSU),
    ("市政府附近", CITY_CENTRE), ("忠州站", STATION), ("火车站", STATION), ("충주 역 근처", STATION),
    ("연수 동", YEONSU), ("시청 앞", CITY_CENTRE), ("near the train station", STATION),
])
def test_place_aliases(text, place):
    assert resolve_location(text) == (place, "text")


@pytest.mark.parametrize("text", ["somewhere", "연수 받는 중", "дома", "在家"])
def test_no_place_named_is_default(text):
    assert resolve_location(text) == (CITY_CENTRE, "default")


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
FEVER_WARNING = {  # fever + headache / stiff neck / rash: AMBER in every language
    "en": ["fever and headache", "fever, stiff neck"], "ru": ["температура и головная боль", "жар, болит голова"],
    "zh": ["发烧头痛", "發燒頭疼"], "ko": ["열과 두통", "열이 나고 머리가 아파요"],
}
MINOR_ESCALATED = ["severe sore throat", "сильно болит горло", "喉咙痛得很严重", "심한 인후통",
                   "sore throat and hard to breathe", "насморк и температура 40"]
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


@pytest.mark.parametrize(("lang", "text"), [(lang, t) for lang in LANGS for t in FEVER_WARNING[lang]])
def test_fever_with_a_warning_sign_is_amber(lang, text):
    result = classify(text)
    assert (result.category, result.severity) == (Category.FEVER, Severity.AMBER)


@pytest.mark.parametrize("text", MINOR_ESCALATED)
def test_minor_complaint_with_a_severity_or_danger_word_is_not_green(text):
    assert classify(text).severity is not Severity.GREEN


@pytest.mark.parametrize("text", UNCLEAR)
def test_unclear_text_is_amber(text):
    result = classify(text)
    assert (result.category, result.severity, result.call_119) == (Category.OTHER, Severity.AMBER, False)


@pytest.mark.parametrize("text", ["небольшой ожог", "小烫伤", "작은 화상", "small burn", "У ребёнка жаром 38",
                                  "mild sore throat", "насморк", "鼻塞", "콧물이 나요"])
def test_minor_cases_can_still_be_green(text):
    assert classify(text).severity is Severity.GREEN  # the fix must not turn everything AMBER


@pytest.mark.asyncio
async def test_demo_chips_through_the_graph_have_no_location_default(use_mcp):
    from backend.app.graph.triage_graph import run_triage
    from backend.app.models.enums import Notice

    use_mcp()
    for lang in LANGS:
        for index, text in enumerate(CHIPS[lang]):
            out = await run_triage(text)
            assert out.location_source == "text" and Notice.LOCATION_DEFAULT not in out.notices, (lang, index)
            assert out.severity is EXPECTED[index][0], (lang, index)
