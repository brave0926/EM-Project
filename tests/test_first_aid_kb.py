"""Validator over the whole first-aid knowledge base (mcp_server/data/first_aid.json)."""

import re

import pytest

from backend.app.models.enums import Category
from backend.app.services import content_safety
from mcp_server.first_aid import LANGUAGES, load_kb

KB = load_kb()
ENTRIES = KB["entries"]
SECTIONS = ("steps", "do_not", "warning_signs", "otc_types")
ENTRY_NAMES = {c.value for c in Category} | {"generic"}


def items(entry):
    return [i for section in SECTIONS for i in entry[section]]


def all_texts():
    for name, entry in ENTRIES.items():
        for i in items(entry):
            for lang in LANGUAGES:
                yield f"{name}/{i['id']}/{lang}", i["text"][lang]
                if "self" in i:
                    yield f"{name}/{i['id']}/self/{lang}", i["self"][lang]
    for key, texts in KB["common"].items():
        for lang in LANGUAGES:
            yield f"common/{key}/{lang}", texts[lang]


def test_entry_names_are_categories():
    assert set(ENTRIES) <= ENTRY_NAMES
    assert {"critical", "burn", "cut", "fever", "minor"} <= set(ENTRIES)


@pytest.mark.parametrize("name", ENTRIES)
def test_entry_shape(name):
    entry = ENTRIES[name]
    assert entry["kind"] in ("standard", "minimal", "generic")
    assert entry["steps"] and entry["warning_signs"], "every entry has steps and warning signs"
    assert entry["sources"] and all(s in KB["sources"] for s in entry["sources"])
    assert entry["reviewed"].keys() == set(LANGUAGES)
    assert not any(entry["reviewed"][lang] for lang in ("ru", "zh", "ko")), "translations are unreviewed drafts"
    if entry["kind"] != "standard":
        assert entry["otc_types"] == [], "minimal and generic entries suggest no products"
    for i in items(entry):
        assert i["id"].startswith(f"{name}.") and re.fullmatch(r"[a-z_]+\.[a-z0-9_]+", i["id"])
        assert i["text"].keys() == set(LANGUAGES) and all(i["text"][lang].strip() for lang in LANGUAGES)
        assert set(i) <= {"id", "text", "self", "match"}
        if "self" in i:  # wording for the injured person (patient=self)
            assert i["self"].keys() == set(LANGUAGES) and all(i["self"][lang].strip() for lang in LANGUAGES)
    for w in entry["warning_signs"]:
        assert w["match"].keys() == {"en", "ru", "cjk"}
        for pattern in w["match"]["ru"]:
            re.compile(pattern)


def test_item_ids_are_unique():
    ids = [i["id"] for entry in ENTRIES.values() for i in items(entry)]
    assert len(ids) == len(set(ids))


@pytest.mark.parametrize(("where", "text"), list(all_texts()))
def test_no_dose_brand_drug_or_diagnosis(where, text):
    assert content_safety.problems(text) == [], where


def test_sources_are_verified_or_marked():
    for key, source in KB["sources"].items():
        if source["verified"]:
            assert source["url"].startswith("https://") and source["publisher"] and source["title"], key
        else:
            assert source["url"] == "UNVERIFIED", key


def test_common_lines_in_every_language():
    for key in ("otc_note", "escalate_line", "no_specific", "not_medical_advice"):
        assert all(KB["common"][key][lang].strip() for lang in LANGUAGES)
    assert all("119" in KB["common"]["escalate_line"][lang] for lang in LANGUAGES)


@pytest.mark.parametrize("bad", ["Take 500 mg", "2 tablets", "服用2片", "타이레놀", "you probably have a fracture",
                                 "ибупрофен", "antibiotics", "진단"])
def test_validator_catches_bad_text(bad):
    assert content_safety.problems(bad)


# Helper wording ("the person", "them") must have a self version, so a writer who is the injured
# person is never told to look after someone else.
HELPER_EN = re.compile(r"\b(the person|them|their|they)\b", re.I)


def test_helper_wording_has_a_self_version():
    missing = [i["id"] for entry in ENTRIES.values() for i in items(entry)
               if HELPER_EN.search(i["text"]["en"]) and "self" not in i]
    assert missing == []


def test_self_versions_are_not_helper_wording():
    for entry in ENTRIES.values():
        for i in items(entry):
            if "self" in i:
                assert not re.search(r"\bthe person\b", i["self"]["en"], re.I), i["id"]
                assert "患者" not in i["self"]["zh"] and "환자" not in i["self"]["ko"], i["id"]
                assert "человек" not in i["self"]["ru"], i["id"]
