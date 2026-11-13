"""Use case: the first-aid card for a triage result. No FastAPI; data only via the MCP client.

- The text comes only from the curated knowledge base (em-mcp-server get_first_aid), never from
  a model. RED always gets a minimal entry (critical, or the high-risk entry of its category).
- A warning sign named in the user's text sets the escalation line ("go to the ER / call 119").
  Severity is never touched here.
- With EM_LLM on, a standard entry may be narrowed to the step/product ids the LLM picks
  (llm_service.select_items, validated); minimal and generic entries are never sent to the LLM.
- Any failure -> no card + FIRST_AID_UNAVAILABLE; the request goes on with the advice template.
"""

from __future__ import annotations

import logging
from time import perf_counter

from backend.app.clients.mcp_client import get_mcp_client
from backend.app.models.domain import TriageResult
from backend.app.models.enums import Category, Language, Notice, Severity
from backend.app.models.first_aid import FirstAidCard, FirstAidGuide, FirstAidStats
from backend.app.services import classifier_service, llm_service, request_timing

log = logging.getLogger(__name__)
# Categories whose entry gives home-care steps: under RED they are replaced by the critical entry.
STANDARD = {Category.BURN, Category.CUT, Category.FEVER, Category.MINOR}


def entry_category(triage: TriageResult) -> Category:
    if triage.severity is Severity.RED and triage.category in STANDARD:
        return Category.CRITICAL
    return triage.category


def matched_warning_signs(query: str, guide: FirstAidGuide) -> list[str]:
    return [w.id for w in guide.warning_signs
            if classifier_service.matches_terms(query, w.match_en, w.match_ru, w.match_cjk)]


async def get_card(query: str, triage: TriageResult, language: Language) -> tuple[FirstAidCard | None, list[Notice]]:
    t0 = perf_counter()
    try:
        guide = await get_mcp_client().get_first_aid(entry_category(triage), language, triage.patient)
    except Exception as exc:  # MCP error, timeout, bad response: the class name only
        log.warning("first aid lookup failed: %s", type(exc).__name__)
        request_timing.note_first_aid(FirstAidStats(ms=_ms(t0), outcome="unavailable"))
        return None, [Notice.FIRST_AID_UNAVAILABLE]

    matched = matched_warning_signs(query, guide)
    steps, otc, selected_by, notices = guide.steps, guide.otc_types, "kb", []
    if guide.kind == "standard":
        ids, job = await llm_service.select_items(
            query, language, [(i.id, i.text) for i in [*steps, *otc]], [s.id for s in steps]
        )
        if ids is not None:
            keep = set(ids)
            steps, otc, selected_by = [s for s in steps if s.id in keep], [o for o in otc if o.id in keep], "llm"
        elif job.outcome in llm_service.FAILED:
            notices.append(Notice.LLM_FALLBACK)

    card = FirstAidCard(
        **guide.model_dump(exclude={"warning_signs", "escalate_line", "steps", "otc_types", "otc_note"}),
        steps=steps,
        otc_types=otc,
        otc_note=guide.otc_note if otc else None,
        warning_signs=[{"id": w.id, "text": w.text} for w in guide.warning_signs],
        escalate=guide.escalate_line if matched else None,
        matched_warning_signs=matched,
        selected_by=selected_by,
    )
    request_timing.note_first_aid(FirstAidStats(
        entry=card.entry, ms=_ms(t0), outcome="ok", generic=card.kind == "generic",
        escalated=bool(matched), selected_by=selected_by,
    ))
    return card, notices


def _ms(t0: float) -> int:
    return max(0, round((perf_counter() - t0) * 1000))
