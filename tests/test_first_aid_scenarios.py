"""Runs eval/scenarios/first_aid.yaml through the whole graph: rules only, and with a fake LLM that
returns invalid ids, valid ids, garbage, a made-up id (for the generic entry) or times out.
Offline: in-process em-mcp-server (mock), fake LLM. Every case must pass in every mode."""

import asyncio
import json
from pathlib import Path

import pytest

from backend.app.clients.llm_client import LlmClient, set_llm_client
from backend.app.graph.triage_graph import run_triage
from backend.app.models.enums import Language
from backend.app.services import content_safety, llm_service

ROOT = Path(__file__).resolve().parents[1]
SCENARIOS = ROOT / "eval" / "scenarios" / "first_aid.yaml"


def load_cases() -> list[dict]:
    text = "\n".join(line for line in SCENARIOS.read_text(encoding="utf-8").splitlines() if not line.startswith("#"))
    return json.loads(text)["cases"]


CASES = load_cases()


class ScenarioLlm(LlmClient):
    """rewrite: unchanged; extract: nothing; select: per mode."""

    def __init__(self, mode: str):
        self.mode, self.select_calls = mode, 0

    async def rewrite_advice(self, advice, language):
        return advice

    async def extract_context(self, query, language):
        return json.dumps({"time": None, "place": None})

    async def select_items(self, query, language, items):
        self.select_calls += 1
        ids = [i for i, _ in items]
        if self.mode == "invalid_ids":
            return json.dumps([ids[0], "made.up", ids[0]])
        if self.mode == "valid_ids":
            steps = [i for i in ids if ".otc_" not in i][:2]
            return json.dumps({"ids": steps + [i for i in ids if ".otc_" in i][:1]})
        if self.mode == "garbage":
            return "Sure! The best items are " + ", ".join(ids[:2])
        if self.mode == "made_up_generic":
            return json.dumps(["generic.made_up"])
        await asyncio.sleep(1.0)  # timeout
        return json.dumps(ids[:1])


MODES = ["rules", "invalid_ids", "valid_ids", "garbage", "made_up_generic", "timeout"]


def test_scenario_file_shape():
    assert len(CASES) == 30 and len({c["id"] for c in CASES}) == 30
    assert {c["lang"] for c in CASES} == {"en", "ru", "zh", "ko"}
    assert sum(c["entry"] == "generic" for c in CASES) >= 8
    entries = {c["entry"] for c in CASES}
    assert {"critical", "burn", "cut", "fever", "minor", "generic", "head_injury", "eye_injury", "bite", "allergy",
            "fracture", "choking", "electric_shock", "drowning", "heavy_bleeding"} <= entries


def card_text(card) -> str:
    parts = [i.text for i in [*card.steps, *card.do_not, *card.warning_signs, *card.otc_types]]
    parts += [card.otc_note or "", card.escalate or "", card.no_specific or "", card.not_medical_advice]
    return "\n".join(parts)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", MODES)
async def test_all_scenarios(use_mcp, monkeypatch, mode):
    use_mcp()
    if mode == "timeout":
        monkeypatch.setattr(llm_service, "LLM_TIMEOUT_S", 0.05)
    failures = []
    for case in CASES:
        set_llm_client(None)  # rules only: the reference severity
        reference = await run_triage(case["text"], language=Language(case["lang"]))
        llm = None
        if mode != "rules":
            llm = ScenarioLlm(mode)
            set_llm_client(llm)
        out = await run_triage(case["text"], language=Language(case["lang"]))
        card, problems = out.first_aid, []
        if card is None:
            failures.append((case["id"], mode, ["no card"]))
            continue
        ids = {i.id for i in [*card.steps, *card.do_not, *card.warning_signs, *card.otc_types]}
        text = card_text(card)
        if card.entry != case["entry"]:
            problems.append(f"entry {card.entry}")
        if "severity" in case and out.severity.value != case["severity"]:
            problems.append(f"severity {out.severity.value}")
        if out.severity is not reference.severity or out.call_119 is not reference.call_119:
            problems.append("the LLM changed severity")
        for need in case["must"]:
            ok = {"escalate": card.escalate is not None, "otc": bool(card.otc_types)}.get(need)
            if ok is None:
                ok = need[7:].lower() in text.lower() if need.startswith("phrase:") else need in ids
            if not ok:
                problems.append(f"missing {need}")
        for bad in case["must_not"]:
            hit = {"otc": bool(card.otc_types), "escalate": card.escalate is not None,
                   "llm": card.selected_by == "llm"}.get(bad)
            if hit is None:
                hit = bad == f"severity:{out.severity.value}"
            if hit:
                problems.append(f"must not {bad}")
        problems += [f"safety {p}" for p in content_safety.problems(text + "\n" + out.advice)]
        if card.kind != "standard" and llm is not None and llm.select_calls:
            problems.append("LLM asked to select for a minimal/generic entry")
        if card.kind == "standard" and mode == "valid_ids" and card.selected_by != "llm":
            problems.append("valid selection not used")
        if card.kind == "standard" and mode in {"invalid_ids", "garbage", "made_up_generic", "timeout"}:
            if card.selected_by != "kb" or len(card.steps) != len(reference.first_aid.steps):
                problems.append("invalid selection was used")
        if problems:
            failures.append((case["id"], mode, problems))
    assert failures == []
