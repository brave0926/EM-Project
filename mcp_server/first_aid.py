"""Curated first-aid knowledge base (mcp_server/data/first_aid.json): static, versioned, reviewed by
hand. Content comes only from this file, never from a model. Loaded once per process."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from backend.app.models.enums import Language
from backend.app.models.first_aid import FirstAidGuide, FirstAidItem, FirstAidSource, WarningSign

KB_PATH = Path(__file__).resolve().parent / "data" / "first_aid.json"
LANGUAGES = ("en", "ru", "zh", "ko")


@lru_cache(maxsize=1)
def load_kb(path: Path = KB_PATH) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def guide(category: str, language: str, patient: str = "unknown") -> FirstAidGuide:
    """The entry for the category in one language; the generic entry when there is none.
    patient "self": items written to the injured person (their "self" text) where the entry has one;
    "other"/"unknown": the helper wording. KeyError when neither entry exists."""
    kb = load_kb()
    entries = kb["entries"]
    name = category if category in entries else "generic"
    entry = entries[name]  # KeyError: no entry and no generic one
    common = kb["common"]

    def text(item: dict[str, Any]) -> str:
        texts = item.get("self") if patient == "self" else None
        return (texts or item["text"])[language]

    def items(section: str) -> list[FirstAidItem]:
        return [FirstAidItem(id=i["id"], text=text(i)) for i in entry[section]]

    otc = items("otc_types")
    return FirstAidGuide(
        entry=name,
        kind=entry["kind"],
        language=Language(language),
        steps=items("steps"),
        do_not=items("do_not"),
        warning_signs=[
            WarningSign(id=w["id"], text=text(w), match_en=w["match"]["en"],
                        match_ru=w["match"]["ru"], match_cjk=w["match"]["cjk"])
            for w in entry["warning_signs"]
        ],
        otc_types=otc,
        otc_note=common["otc_note"][language] if otc else None,
        no_specific=common["no_specific"][language] if entry["kind"] == "generic" else None,
        not_medical_advice=common["not_medical_advice"][language],
        escalate_line=common["escalate_line"][language],
        sources=[FirstAidSource(id=s, **kb["sources"][s]) for s in entry["sources"]],
        reviewed=entry["reviewed"][language],
    )
