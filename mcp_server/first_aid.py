"""Curated first-aid knowledge base (mcp_server/data/first_aid.json): static, versioned, reviewed by
hand. Content comes only from this file, never from a model. Loaded once per process."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

KB_PATH = Path(__file__).resolve().parent / "data" / "first_aid.json"
LANGUAGES = ("en", "ru", "zh", "ko")


@lru_cache(maxsize=1)
def load_kb(path: Path = KB_PATH) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))
