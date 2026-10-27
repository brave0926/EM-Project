"""Minimal .env loader (stdlib only). Bottom layer: imports nothing from the app."""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def parse_env(text: str) -> dict[str, str]:
    """Parse KEY=VALUE lines; skips blanks and comments, strips `export` and matching quotes."""
    values: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):]
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key:
            values[key] = value
    return values


def load_env(path: Path | None = None) -> None:
    """Load .env into os.environ. Variables already set in the environment win."""
    path = path or ROOT / ".env"
    if not path.is_file():
        return
    for key, value in parse_env(path.read_text(encoding="utf-8")).items():
        os.environ.setdefault(key, value)
