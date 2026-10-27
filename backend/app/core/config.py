"""Application settings. Bottom layer: imports nothing from the app."""

from __future__ import annotations

import os
from datetime import timedelta, timezone

from pydantic import BaseModel, Field

from backend.app.core.env import ROOT

STALE_AFTER_MIN = 180  # RT-104: data older than this is UNCERTAIN
TOOL_TIMEOUT_S = 2.0  # RT-102: one MCP tool call
FALLBACK_BUDGET_S = 0.2  # RT-103: serving the last good data after a failure
BREAKER_FAILURES = 3  # consecutive failures that open a tool's circuit
BREAKER_OPEN_S = 30.0  # how long an open circuit skips upstream calls
LLM_TIMEOUT_S = 1.0  # advice rewrite budget; the template is used if the LLM is slower
DEFAULT_REGION = "Chungju"
KST = timezone(timedelta(hours=9))  # local time for opening hours (no DST in Korea)


class Settings(BaseModel):
    title: str = "EM-Agent API"
    description: str = (
        "Real-time emergency triage and facility dispatch. Finds the nearest ER with free "
        "beds and the nearest open pharmacy. Not medical advice; call 119 in an emergency."
    )
    version: str = "0.1.0"
    mcp_url: str = Field(default_factory=lambda: os.environ.get("EM_MCP_URL", "http://127.0.0.1:8001/mcp"))
    fallback_db: str = Field(  # SQLite file with the last good facility data (*.db is gitignored)
        default_factory=lambda: os.environ.get("EM_FALLBACK_DB", str(ROOT / "em_fallback.db"))
    )


settings = Settings()
