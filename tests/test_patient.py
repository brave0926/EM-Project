"""Who is hurt (patient_service): the wording of advice and first aid follows it; severity never does."""

import pytest

from backend.app.models.domain import TriageResult
from backend.app.models.enums import Category, Language, Patient, Severity
from backend.app.services import advice_service, classifier_service
from backend.app.services.patient_service import detect_patient
from mcp_server import first_aid

SELF, OTHER, UNKNOWN = Patient.SELF, Patient.OTHER, Patient.UNKNOWN

CASES = [
    # English
    ("I burned my hand near Chungju Station", SELF),
    ("Severe burn on my hand", SELF),
    ("I'm bleeding a lot and feel dizzy", SELF),
    ("I can’t breathe", SELF),
    ("My friend has a severe burn on his hand", OTHER),
    ("My son cut his finger", OTHER),
    ("She can't breathe", OTHER),
    ("I am with my friend, he cut his arm", OTHER),
    ("There is a man lying on the street", OTHER),
    ("Chest pain, hard to breathe", UNKNOWN),
    ("the burn is bad", UNKNOWN),
    # Russian
    ("Я обжёг руку", SELF),
    ("У меня сильная боль в груди", SELF),
    ("У друга ожог руки", OTHER),
    ("Мой сын порезался", OTHER),
    ("Она не дышит", OTHER),
    ("Ожог руки у вокзала", UNKNOWN),
    # Chinese
    ("我的手严重烧伤了", SELF),
    ("我们在忠州站附近，我发烧了", SELF),
    ("其他地方没事，我头疼", SELF),
    ("我的朋友手部严重烧伤", OTHER),
    ("他胸痛", OTHER),
    ("我们在忠州站附近", UNKNOWN),
    ("手部严重烧伤,忠州站附近", UNKNOWN),
    # Korean
    ("제가 손에 화상을 입었어요", SELF),
    ("내 손에 심한 화상", SELF),
    ("친구가 손에 화상을 입었어요", OTHER),
    ("아이가 열이 나요", OTHER),
    ("손에 심한 화상, 충주역 근처", UNKNOWN),
]


@pytest.mark.parametrize(("text", "expected"), CASES)
def test_detect_patient(text, expected):
    assert detect_patient(text) is expected


@pytest.mark.parametrize(("text", "expected"), CASES)
def test_classify_sets_patient_and_keeps_severity(text, expected):
    result = classifier_service.classify(text)
    assert result.patient is expected
    assert result.model_copy(update={"patient": UNKNOWN}) == classifier_service._classify(text)


@pytest.mark.parametrize("language", list(Language))
def test_first_aid_self_wording(language):
    other = first_aid.guide("choking", language.value, "other")
    unknown = first_aid.guide("choking", language.value)
    mine = first_aid.guide("choking", language.value, "self")
    assert other == unknown
    assert [i.id for i in mine.steps] == [i.id for i in other.steps]  # same items, other words
    kb = {i["id"]: i for i in first_aid.load_kb()["entries"]["choking"]["steps"]}
    for item in mine.steps:
        assert item.text == kb[item.id].get("self", kb[item.id]["text"])[language.value]
    assert mine.steps != other.steps


def test_entries_without_self_text_are_the_same_for_self():
    assert first_aid.guide("burn", "en", "self") == first_aid.guide("burn", "en", "other")


@pytest.mark.parametrize("language", list(Language))
def test_critical_advice_line_follows_the_patient(language):
    def advice(patient):
        triage = TriageResult(category=Category.CRITICAL, severity=Severity.RED, call_119=True, patient=patient)
        return advice_service.build_advice(language, triage, [], [], [], [])

    mine, other = advice(SELF), advice(OTHER)
    assert mine != other and advice(UNKNOWN) == other
    assert advice_service.prompt_119(language) in mine  # the 119 line is never dropped
    if language is Language.EN:
        assert "Stay with the person" in other and "the person" not in mine
