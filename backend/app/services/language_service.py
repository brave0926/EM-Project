"""Detect the query language from its script. Pure: no I/O, no FastAPI."""

from __future__ import annotations

import re

from backend.app.models.enums import Language

_HANGUL = re.compile(r"[가-힣ᄀ-ᇿ㄰-㆏]")
_CJK = re.compile(r"[一-鿿]")
_CYRILLIC = re.compile(r"[Ѐ-ӿ]")


def detect_language(text: str) -> Language:
    """Hangul -> ko, Chinese characters -> zh, Cyrillic -> ru, otherwise en."""
    if _HANGUL.search(text):
        return Language.KO  # checked before CJK: Korean text may contain hanja
    if _CJK.search(text):
        return Language.ZH
    if _CYRILLIC.search(text):
        return Language.RU
    return Language.EN
