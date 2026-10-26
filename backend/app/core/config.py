"""Application settings. Bottom layer: imports nothing from the app."""

from __future__ import annotations

from pydantic import BaseModel

STALE_AFTER_MIN = 180  # RT-104: data older than this is UNCERTAIN


class Settings(BaseModel):
    title: str = "EM-Agent API"
    description: str = (
        "Real-time emergency triage and facility dispatch. Finds the nearest ER with free "
        "beds and the nearest open pharmacy. Not medical advice; call 119 in an emergency."
    )
    version: str = "0.1.0"


settings = Settings()
