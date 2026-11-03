"""Use case: the two LLM jobs with budget, validation and fallback. No FastAPI, no I/O of its own.

Every job runs inside LLM_TIMEOUT_S (less if RT-105 is near) and is checked before use; on any
error, timeout, empty or invalid output the caller keeps its rule/template result. The LLM never
decides severity or 119. Logs only job, outcome and latency, never the user's text or the key.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import Awaitable, Callable, Sequence
from time import perf_counter

from pydantic import ValidationError

from backend.app.clients.llm_client import get_llm_client
from backend.app.core.config import END_TO_END_S, LLM_RESERVE_S, LLM_REWRITE_MAX_CHARS, LLM_TIMEOUT_S
from backend.app.models.enums import Language, LlmOutcome
from backend.app.models.llm import LlmContext, LlmJob
from backend.app.services import request_timing

log = logging.getLogger(__name__)
FAILED = {LlmOutcome.TIMEOUT, LlmOutcome.INVALID, LlmOutcome.ERROR}
# Drug amounts the rewrite must not introduce (EN/RU/ZH/KO units).
_DOSE = re.compile(
    r"\d\s*(mg|mcg|µg|ml|iu|g\b|мг|мл|毫克|毫升|克|밀리그램|밀리리터|그램)|\d\s*(tablets?|pills?|таблет|片|알|정\b)",
    re.IGNORECASE,
)
# Diagnoses the rewrite must not introduce ("you probably have ...", "диагноз", "诊断", "진단").
_DIAGNOSIS = re.compile(
    r"diagnos|\byou (?:most )?(?:likely |probably |may )?(?:have|suffer from|are having) (?:a|an)\b"
    r"|\b(?:it|this) (?:is|looks like) (?:most )?(?:likely|probably) (?:a|an)\b"
    r"|диагноз|у вас,? (?:вероятно|скорее всего|похоже)|(?:это|похоже,?) (?:похоже на|скорее всего)"
    r"|诊断|你(?:可能|应该)?(?:患有|得了)|(?:很)?可能是.{0,6}(?:病|症|骨折|中风|心脏病)"
    r"|진단|(?:인|일) 것 같습니다|(?:으로|로) 보입니다|가능성이 높습니다",
    re.IGNORECASE,
)


class _Invalid(Exception):
    pass


def enabled() -> bool:
    """True when an LLM is configured (EM_LLM=anthropic with a key, or a test client)."""
    return get_llm_client().enabled


def budget_s() -> float:
    """LLM_TIMEOUT_S, cut so the job ends LLM_RESERVE_S before the RT-105 limit of this request."""
    timing = request_timing.current()
    if timing is None:
        return LLM_TIMEOUT_S
    return min(LLM_TIMEOUT_S, END_TO_END_S - LLM_RESERVE_S - timing.elapsed_s())


async def _run(job: str, call: Callable[[], Awaitable[str]], check: Callable[[str], object]) -> tuple[object, LlmJob]:
    if not enabled():
        return None, LlmJob(outcome=LlmOutcome.OFF)
    budget = budget_s()
    t0 = perf_counter()
    value, outcome = None, LlmOutcome.OK
    if budget <= 0:
        outcome = LlmOutcome.TIMEOUT  # no time left: never start a call that would break RT-105
    else:
        try:
            value = check(await asyncio.wait_for(call(), budget))
        except TimeoutError:
            outcome = LlmOutcome.TIMEOUT
        except _Invalid:
            outcome = LlmOutcome.INVALID
        except Exception as exc:  # SDK, network, refusal: the class name only, never the message
            log.info("llm %s error %s", job, type(exc).__name__)
            outcome = LlmOutcome.ERROR
    ms = max(0, round((perf_counter() - t0) * 1000)) if budget > 0 else None
    log.info("llm %s %s %s ms", job, outcome.value, ms)
    request_timing.note_llm(job, ms, outcome)
    return value, LlmJob(outcome=outcome, ms=ms)


def check_rewrite(text: str, template: str, required: Sequence[str]) -> str:
    """The rewrite is used only if it is non-empty, not too long, keeps every required string
    (facility names, phones, the RED 119 line), mentions 119 like the template, and adds no dose
    and no diagnosis."""
    text = text.strip()
    if not text or len(text) > LLM_REWRITE_MAX_CHARS:
        raise _Invalid
    if any(r not in text for r in required):
        raise _Invalid
    if "119" in template and "119" not in text:
        raise _Invalid
    if _DOSE.search(text) and not _DOSE.search(template):
        raise _Invalid
    if _DIAGNOSIS.search(text) and not _DIAGNOSIS.search(template):
        raise _Invalid
    return text


async def rewrite_advice(template: str, language: Language, required: Sequence[str] = ()) -> tuple[str, LlmJob]:
    """(advice to show, job). The template comes back on any failure."""
    text, job = await _run(
        "rewrite",
        lambda: get_llm_client().rewrite_advice(template, language),
        lambda out: check_rewrite(out, template, required),
    )
    return (text if isinstance(text, str) else template), job


def parse_context(raw: str) -> LlmContext:
    try:
        return LlmContext.model_validate(json.loads(raw))
    except (ValueError, ValidationError):  # json.JSONDecodeError is a ValueError
        raise _Invalid from None


async def extract_context(query: str, language: Language) -> tuple[LlmContext | None, LlmJob]:
    """(time/place the LLM read from the query, or None, job). The caller fills only what the rules
    did not find; a place is a known place id, never coordinates."""
    ctx, job = await _run("extract", lambda: get_llm_client().extract_context(query, language), parse_context)
    return (ctx if isinstance(ctx, LlmContext) else None), job
