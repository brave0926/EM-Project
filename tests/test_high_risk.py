"""High-risk injuries and cases outside the knowledge base (EN/RU/ZH/KO, offline)."""

import pytest

from backend.app.clients.mcp_client import get_mcp_client
from backend.app.models.domain import TriageResult
from backend.app.models.enums import Category, Language, Severity
from backend.app.services import first_aid_service
from backend.app.services.classifier_service import FIXED_SEVERITY, classify

C, S = Category, Severity
# (text, category, severity) - every high-risk category in every language
HIGH_RISK = [
    ("He hit his head and feels sleepy", C.HEAD_INJURY, S.AMBER), ("Он ударился головой", C.HEAD_INJURY, S.AMBER),
    ("孩子摔到头了", C.HEAD_INJURY, S.AMBER), ("아이가 머리를 부딪쳤어요", C.HEAD_INJURY, S.AMBER),
    ("bleach splashed in my eye", C.EYE_INJURY, S.AMBER), ("попало в глаз средство", C.EYE_INJURY, S.AMBER),
    ("清洁剂进了眼睛", C.EYE_INJURY, S.AMBER), ("눈에 세제가 들어갔어요", C.EYE_INJURY, S.AMBER),
    ("a dog bit me, bite on the leg", C.BITE, S.AMBER), ("укусила собака", C.BITE, S.AMBER),
    ("被狗咬了", C.BITE, S.AMBER), ("개에게 물렸어요", C.BITE, S.AMBER),
    ("snake bite on the ankle", C.BITE, S.RED), ("укусила змея", C.BITE, S.RED),
    ("被蛇咬了", C.BITE, S.RED), ("뱀에 물렸어요", C.BITE, S.RED),
    ("allergic reaction with hives", C.ALLERGY, S.AMBER), ("аллергия, крапивница", C.ALLERGY, S.AMBER),
    ("过敏起荨麻疹", C.ALLERGY, S.AMBER), ("알레르기로 두드러기가 났어요", C.ALLERGY, S.AMBER),
    ("allergic, swollen lips and tongue", C.ALLERGY, S.RED), ("аллергия, отёк губ", C.ALLERGY, S.RED),
    ("过敏，嘴唇肿了", C.ALLERGY, S.RED), ("알레르기, 입술이 부었어요", C.ALLERGY, S.RED),
    ("my child is choking on food", C.CHOKING, S.RED), ("ребёнок подавился", C.CHOKING, S.RED),
    ("孩子噎住了", C.CHOKING, S.RED), ("아이가 사레들려 목에 걸렸어요", C.CHOKING, S.RED),
    ("broken arm, bone sticking out", C.FRACTURE, S.AMBER), ("перелом ноги", C.FRACTURE, S.AMBER),
    ("手臂骨折了", C.FRACTURE, S.AMBER), ("다리가 부러졌어요", C.FRACTURE, S.AMBER),
    ("electric shock from a socket", C.ELECTRIC_SHOCK, S.RED), ("ударило током", C.ELECTRIC_SHOCK, S.RED),
    ("他触电了", C.ELECTRIC_SHOCK, S.RED), ("감전됐어요", C.ELECTRIC_SHOCK, S.RED),
    ("child nearly drowned in the pool", C.DROWNING, S.RED), ("ребёнок тонул в бассейне", C.DROWNING, S.RED),
    ("孩子溺水了", C.DROWNING, S.RED), ("아이가 물에 빠졌어요", C.DROWNING, S.RED),
    ("heavy bleeding, it won't stop", C.HEAVY_BLEEDING, S.RED), ("сильное кровотечение", C.HEAVY_BLEEDING, S.RED),
    ("血流不止", C.HEAVY_BLEEDING, S.RED), ("피가 멈추지 않아요", C.HEAVY_BLEEDING, S.RED),
]
OUT_OF_BASE = ["insect in my ear", "в ухо залез жук", "虫子进了耳朵", "귀에 벌레가 들어갔어요",
               "knocked out a tooth", "выбил зуб", "牙齿被撞掉了", "이가 부러졌어요",
               "swallowed a coin", "застряла заноза"]


@pytest.mark.parametrize(("text", "category", "severity"), HIGH_RISK)
def test_high_risk_category_and_severity(text, category, severity):
    result = classify(text)
    assert (result.category, result.severity, result.call_119) == (category, severity, severity is S.RED)


def test_every_high_risk_category_is_covered_in_four_languages():
    for category in FIXED_SEVERITY:
        assert sum(c is category for _, c, _ in HIGH_RISK) >= 4, category


@pytest.mark.parametrize("text", OUT_OF_BASE)
def test_out_of_base_is_other_and_amber(text):
    result = classify(text)
    assert result.severity is not S.GREEN
    assert result.category in {C.OTHER, *FIXED_SEVERITY}  # e.g. "swallowed" may lift to AMBER, never GREEN


@pytest.mark.asyncio
@pytest.mark.parametrize("category", list(FIXED_SEVERITY))
async def test_high_risk_entries_are_minimal_without_products(use_mcp, category):
    use_mcp()
    for language in Language:
        guide = await get_mcp_client().get_first_aid(category, language)
        assert guide.entry == category.value and guide.kind == "minimal" and guide.otc_types == []
        assert any("119" in s.text or "119" in w.text for s in guide.steps for w in guide.warning_signs)


@pytest.mark.asyncio
@pytest.mark.parametrize("language", list(Language))
async def test_other_gets_the_generic_entry(use_mcp, language):
    use_mcp()
    triage = TriageResult(category=C.OTHER, severity=S.AMBER, call_119=False)
    card, notices = await first_aid_service.get_card("insect in my ear", triage, language)
    assert card.entry == "generic" and card.kind == "generic" and card.no_specific and card.otc_types == []
    assert [s.id for s in card.steps] == ["generic.stay", "generic.watch", "generic.go_er", "generic.pharmacist"]
    assert notices == []
