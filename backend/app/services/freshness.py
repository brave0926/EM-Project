"""RT-104 freshness rule. Pure: no I/O, no FastAPI."""

from __future__ import annotations

from datetime import datetime, timezone

from backend.app.core.config import STALE_AFTER_MIN
from backend.app.models.enums import DataStatus


def age_minutes(fetched_at: datetime, now: datetime | None = None) -> float:
    """Minutes since fetched_at. Naive datetimes are treated as UTC."""
    if fetched_at.tzinfo is None:
        fetched_at = fetched_at.replace(tzinfo=timezone.utc)
    now = now or datetime.now(timezone.utc)
    return (now - fetched_at).total_seconds() / 60


def freshness_status(
    status: DataStatus, fetched_at: datetime, now: datetime | None = None
) -> DataStatus:
    """RT-104: data older than 180 minutes is UNCERTAIN regardless of source."""
    if age_minutes(fetched_at, now) > STALE_AFTER_MIN:
        return DataStatus.UNCERTAIN
    return status
