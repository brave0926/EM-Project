import pytest

from backend.app.models.enums import Category, Language, Severity
from backend.app.services.classifier_service import classify
from backend.app.services.language_service import detect_language

C, S = Category, Severity


@pytest.mark.parametrize(
    ("text", "language"),
    [
        ("Severe burn on my hand", Language.EN),
        ("Сильный ожог руки", Language.RU),
        ("手被严重烫伤了", Language.ZH),
        ("손에 심한 화상을 입었어요", Language.KO),
        ("충주역 근처, 发烧", Language.KO),  # Hangul wins over Chinese characters
        ("ожог near Chungju", Language.RU),
        ("", Language.EN),
    ],
)
def test_detect_language(text, language):
    assert detect_language(text) is language


@pytest.mark.parametrize(
    ("text", "category", "severity"),
    [
        # critical -> red in every language
        ("My father is unconscious and not breathing", C.CRITICAL, S.RED),
        ("Sudden chest pain", C.CRITICAL, S.RED),
        ("Мама без сознания", C.CRITICAL, S.RED),
        ("他昏迷了", C.CRITICAL, S.RED),
        ("아버지가 의식이 없어요", C.CRITICAL, S.RED),
        ("heavy bleeding from the leg", C.CRITICAL, S.RED),  # beats plain "bleeding" (cut)
        # burn
        ("Severe burn on my hand, near Chungju Station, 2 AM", C.BURN, S.AMBER),
        ("small burn from the oven", C.BURN, S.GREEN),
        ("Обжёг палец, большой волдырь", C.BURN, S.AMBER),
        ("手被烫伤了", C.BURN, S.GREEN),
        ("손에 화상, 물집이 생겼어요", C.BURN, S.AMBER),
        # cut
        ("small cut on my finger", C.CUT, S.GREEN),
        ("deep cut, bleeding", C.CUT, S.AMBER),
        ("Порезал руку ножом", C.CUT, S.GREEN),
        ("手指割伤了", C.CUT, S.GREEN),
        ("손을 칼에 베였어요", C.CUT, S.GREEN),
        # fever: 39.5 °C or more is amber, with or without a unit
        ("fever 38.2 since morning", C.FEVER, S.GREEN),
        ("fever 40 for 2 days", C.FEVER, S.AMBER),
        ("fever since 40 minutes ago", C.FEVER, S.GREEN),  # 40 minutes is not 40 °C
        ("У ребёнка жар 39,8", C.FEVER, S.AMBER),
        ("发烧39.6度", C.FEVER, S.AMBER),
        ("열이 38도", C.FEVER, S.GREEN),
        ("열이 40도 넘어요", C.FEVER, S.AMBER),
        # unrecognised -> amber, never green
        ("my stomach hurts", C.OTHER, S.AMBER),
        ("пожар в доме", C.OTHER, S.AMBER),  # "пожар" (fire) must not match "жар" (fever)
        ("acute pain", C.OTHER, S.AMBER),  # "acute" must not match "cut"
    ],
)
def test_classify(text, category, severity):
    result = classify(text)
    assert (result.category, result.severity) == (category, severity)
    assert result.call_119 is (severity is S.RED)


@pytest.mark.parametrize("text", ["", "hello", "???", "도와주세요", "помогите", "救命"])
def test_unclear_text_is_never_green(text):
    assert classify(text).severity is not S.GREEN
