"""Use case: generic first-aid items for a category. Pure: no FastAPI."""

from __future__ import annotations

from backend.app.clients.mcp_client import get_mcp_client
from backend.app.models.domain import OtcAdvice
from backend.app.models.enums import Category


async def get_otc_advice(category: Category) -> OtcAdvice:
    if category is Category.CRITICAL:
        # Never let an MCP outage or delay hold back the 119 prompt.
        return OtcAdvice(category=category, items=[], call_119=True)
    items = await get_mcp_client().get_otc(category)
    return OtcAdvice(category=category, items=items, call_119=False)
