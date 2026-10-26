"""Application settings. Bottom layer: imports nothing from the app."""

from __future__ import annotations

import os

from pydantic import BaseModel, Field

STALE_AFTER_MIN = 180  # RT-104: data older than this is UNCERTAIN
TOOL_TIMEOUT_S = 2.0  # RT-102: one MCP tool call


class Settings(BaseModel):
    title: str = "EM-Agent API"
    description: str = (
        "Real-time emergency triage and facility dispatch. Finds the nearest ER with free "
        "beds and the nearest open pharmacy. Not medical advice; call 119 in an emergency."
    )
    version: str = "0.1.0"
    mcp_url: str = Field(default_factory=lambda: os.environ.get("EM_MCP_URL", "http://127.0.0.1:8001/mcp"))


settings = Settings()
