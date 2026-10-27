"""Circuit breaker + last-good-data fallback around MCP tool calls. No FastAPI.

A successful call is saved to the fallback store. A failed call, or any call while the tool's
circuit is OPEN, is answered from the store within RT-103 (200 ms) with status CACHED and the
original fetched_at, so RT-104 still marks old data UNCERTAIN. Without saved data the original
McpClientError is raised (an open circuit raises UNAVAILABLE), so endpoints keep their 5xx mapping.
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from time import monotonic
from typing import Any, Generic, Literal, TypeVar

from pydantic import ValidationError

from backend.app.clients.fallback_store import StoredResult, get_fallback_store
from backend.app.clients.mcp_client import McpClientError
from backend.app.core.config import FALLBACK_BUDGET_S
from backend.app.models.domain import ERFacility, PharmacyFacility
from backend.app.models.enums import DataStatus
from backend.app.services.circuit_breaker import CircuitBreaker

log = logging.getLogger(__name__)
F = TypeVar("F", ERFacility, PharmacyFacility)
Tool = Literal["er", "pharmacy"]
TOOLS: tuple[Tool, ...] = ("er", "pharmacy")

_breakers: dict[Tool, CircuitBreaker] = {}


def reset_breakers(clock: Callable[[], float] = monotonic) -> None:
    """Fresh CLOSED breakers (app start; tests pass a fake clock)."""
    _breakers.clear()
    _breakers.update({tool: CircuitBreaker(clock=clock) for tool in TOOLS})


def breaker(tool: Tool) -> CircuitBreaker:
    if tool not in _breakers:
        reset_breakers()
    return _breakers[tool]


def breaker_status() -> dict[str, dict[str, Any]]:
    """Per tool: state, consecutive failures, last error code (no URLs, no keys)."""
    return {
        tool: {"state": b.state, "failures": b.failures, "last_error": b.last_error}
        for tool in TOOLS
        for b in [breaker(tool)]
    }


@dataclass
class Fetched(Generic[F]):
    items: list[F]
    from_cache: bool = False
    meta: dict[str, Any] = field(default_factory=dict)  # saved with the items (e.g. at_time)


async def fetch_or_fallback(
    tool: Tool,
    key: str,
    fetch: Callable[[], Awaitable[list[F]]],
    model: type[F],
    meta: dict[str, Any] | None = None,
) -> Fetched[F]:
    b = breaker(tool)
    if b.allow():
        try:
            items = await fetch()
        except McpClientError as exc:
            b.record_failure(exc.code)
            error = exc
        except BaseException:
            b.release()
            raise
        else:
            b.record_success()
            await _save(tool, key, items, meta or {})
            return Fetched(items)
    else:
        error = McpClientError("UNAVAILABLE", f"{tool}: circuit open, upstream skipped")
    saved = await _load(tool, key)
    if saved is None:
        raise error
    try:
        cached = [model.model_validate(_as_cached(item)) for item in saved.items]
    except ValidationError:  # saved by an older model version
        log.warning("fallback data for %s no longer validates", tool)
        raise error from None
    return Fetched(cached, from_cache=True, meta=saved.meta)


def _as_cached(item: dict[str, Any]) -> dict[str, Any]:
    # keeps fetched_at; the model re-applies RT-104, so old data becomes UNCERTAIN
    if item.get("status") != DataStatus.UNCERTAIN:
        item = {**item, "status": DataStatus.CACHED}
    return item


async def _save(tool: Tool, key: str, items: list[F], meta: dict[str, Any]) -> None:
    try:
        await get_fallback_store().save(tool, key, [i.model_dump(mode="json") for i in items], meta)
    except (OSError, sqlite3.Error):  # the live answer still goes out
        log.warning("fallback save failed for %s", tool, exc_info=True)


async def _load(tool: Tool, key: str) -> StoredResult | None:
    try:
        return await asyncio.wait_for(get_fallback_store().load(tool, key), FALLBACK_BUDGET_S)
    except (TimeoutError, OSError, sqlite3.Error, ValueError):  # slow or broken store: no fallback
        log.warning("fallback load failed for %s", tool, exc_info=True)
        return None
