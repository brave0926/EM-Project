"""Supervisor graph for triage (LangGraph).

    START -> triage -+- red:   er_worker ----------------------+-> advise -> END
                     +- other: er_worker || pharmacy_worker ---+

triage classifies the query with rules (no network, fast first answer). The workers run in
parallel and reach data only through services -> MCP client. A failed lookup is answered from
the last saved data (FALLBACK_CACHE) or, with nothing saved, adds UNAVAILABLE + NO_DATA instead
of failing the request: severity, advice and the 119 prompt always come back.
"""

from __future__ import annotations

import asyncio
import logging
import operator
import time
from collections.abc import AsyncIterator
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph

from backend.app.core.config import DEFAULT_REGION
from backend.app.models.domain import (
    ERFacility,
    Location,
    LocationSource,
    PharmacyFacility,
    TriageOutcome,
    TriageResult,
)
from backend.app.models.enums import Language, Notice, Severity
from backend.app.services import (
    advice_service,
    classifier_service,
    er_facility_service,
    language_service,
    location_service,
    otc_service,
    pharmacy_facility_service,
    time_service,
)

log = logging.getLogger(__name__)
TOP_N = 3  # facilities returned per kind


class TriageState(TypedDict, total=False):
    # input
    query: str
    language: Language | None
    lat: float | None
    lon: float | None
    at_time: str | None
    # filled by the nodes
    requested_time: str | None  # time asked for (request or text); None = now
    triage: TriageResult
    location: Location
    location_source: LocationSource
    er: list[ERFacility]
    pharmacies: list[PharmacyFacility]
    otc: list[str]
    notices: Annotated[list[Notice], operator.add]  # parallel workers append
    advice: str


async def triage_node(state: TriageState) -> TriageState:
    query = state["query"]
    location, source = location_service.resolve_location(query, state.get("lat"), state.get("lon"))
    at_time = state.get("at_time") or time_service.parse_time(query)
    return {
        "language": state.get("language") or language_service.detect_language(query),
        "triage": classifier_service.classify(query),
        "location": location,
        "location_source": source,
        "at_time": at_time,
        "requested_time": at_time,
        "notices": [Notice.LOCATION_DEFAULT] if source == "default" else [],
    }


def route(state: TriageState) -> list[str]:
    if state["triage"].severity is Severity.RED:
        return ["er_worker"]  # critical: 119 first, skip the pharmacy
    return ["er_worker", "pharmacy_worker"]


async def er_worker(state: TriageState) -> TriageState:
    loc = state["location"]
    try:
        ers, notices = await er_facility_service.find_ers(DEFAULT_REGION, loc.lat, loc.lon)
    except Exception:
        log.warning("er_worker failed", exc_info=True)
        return {"er": [], "notices": [Notice.ER_UNAVAILABLE, Notice.NO_DATA]}
    ers = ers[:TOP_N]  # free beds first, then nearest
    if not any(e.hvec > 0 for e in ers):
        notices.append(Notice.NO_FREE_ER_BEDS)
    return {"er": ers, "notices": notices}


async def pharmacy_worker(state: TriageState) -> TriageState:
    loc = state["location"]
    pharmacies, otc = await asyncio.gather(
        pharmacy_facility_service.find_open_pharmacies(loc.lat, loc.lon, state.get("at_time")),
        otc_service.get_otc_advice(state["triage"].category),
        return_exceptions=True,
    )
    update: TriageState = {"pharmacies": [], "otc": [], "notices": []}
    if isinstance(pharmacies, BaseException):  # gather may also return CancelledError
        log.warning("pharmacy lookup failed", exc_info=pharmacies)
        update["notices"] += [Notice.PHARMACY_UNAVAILABLE, Notice.NO_DATA]
    else:
        update["at_time"], found, notices = pharmacies
        update["pharmacies"] = found[:TOP_N]
        update["notices"] += notices
        if not any(p.is_open for p in found):  # empty, or only closed / unknown hours
            update["notices"].append(Notice.NO_OPEN_PHARMACY)
    if isinstance(otc, BaseException):
        log.warning("otc lookup failed", exc_info=otc)
        update["notices"].append(Notice.OTC_UNAVAILABLE)
    else:
        update["otc"] = otc.items
    return update


async def advise(state: TriageState) -> TriageState:
    er, pharmacies = state.get("er", []), state.get("pharmacies", [])
    extra = advice_service.data_notices(er, pharmacies)
    notices = list(dict.fromkeys([*state.get("notices", []), *extra]))
    text = advice_service.build_advice(
        state["language"], state["triage"], er, pharmacies, state.get("otc", []), notices,
        state.get("requested_time"),
    )
    return {"advice": await advice_service.polish_advice(text, state["language"]), "notices": extra}


def build_graph():
    graph = StateGraph(TriageState)
    graph.add_node("triage", triage_node)
    graph.add_node("er_worker", er_worker)
    graph.add_node("pharmacy_worker", pharmacy_worker)
    graph.add_node("advise", advise)
    graph.add_edge(START, "triage")
    graph.add_conditional_edges("triage", route, ["er_worker", "pharmacy_worker"])
    graph.add_edge("er_worker", "advise")
    graph.add_edge("pharmacy_worker", "advise")
    graph.add_edge("advise", END)
    return graph.compile()


_graph = build_graph()


def _input(
    query: str, language: Language | None, lat: float | None, lon: float | None, at_time: str | None
) -> TriageState:
    return {"query": query, "language": language, "lat": lat, "lon": lon, "at_time": at_time, "notices": []}


def stream_updates(
    query: str,
    language: Language | None = None,
    lat: float | None = None,
    lon: float | None = None,
    at_time: str | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Node updates as each node finishes ({node: update}); the parallel workers in either order.
    Closing the iterator cancels the nodes still running."""
    return _graph.astream(_input(query, language, lat, lon, at_time), stream_mode="updates")


async def run_triage(
    query: str,
    language: Language | None = None,
    lat: float | None = None,
    lon: float | None = None,
    at_time: str | None = None,
) -> TriageOutcome:
    t0 = time.perf_counter()
    state = await _graph.ainvoke(_input(query, language, lat, lon, at_time))
    triage = state["triage"]
    return TriageOutcome(
        language=state["language"],
        category=triage.category,
        severity=triage.severity,
        call_119=triage.call_119,
        location=state["location"],
        location_source=state["location_source"],
        at_time=state.get("at_time") if triage.severity is not Severity.RED else None,
        er=state.get("er", []),
        pharmacies=state.get("pharmacies", []),
        otc=state.get("otc", []),
        notices=list(dict.fromkeys(state.get("notices", []))),
        advice=state["advice"],
        total_ms=round((time.perf_counter() - t0) * 1000),
    )
