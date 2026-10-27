"""Circuit breaker for one upstream tool. Pure: no I/O, no FastAPI; the clock is injectable.

    CLOSED --3 consecutive failures--> OPEN --30 s--> HALF_OPEN --trial ok--> CLOSED
                                        ^                  |
                                        +--trial fails-----+
"""

from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum
from time import monotonic

from backend.app.core.config import BREAKER_FAILURES, BREAKER_OPEN_S


class BreakerState(StrEnum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class CircuitBreaker:
    def __init__(
        self,
        threshold: int = BREAKER_FAILURES,
        open_s: float = BREAKER_OPEN_S,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        self.threshold = threshold
        self.open_s = open_s
        self._clock = clock
        self._state = BreakerState.CLOSED
        self._opened_at = 0.0
        self._trial = False  # a HALF_OPEN trial call is in flight
        self.failures = 0  # consecutive
        self.last_error: str | None = None  # error code only, never a message

    @property
    def state(self) -> BreakerState:
        if self._state is BreakerState.OPEN and self._clock() - self._opened_at >= self.open_s:
            self._state = BreakerState.HALF_OPEN
        return self._state

    def allow(self) -> bool:
        """May this call go upstream? HALF_OPEN lets exactly one trial through."""
        state = self.state
        if state is BreakerState.CLOSED:
            return True
        if state is BreakerState.HALF_OPEN and not self._trial:
            self._trial = True
            return True
        return False

    def record_success(self) -> None:
        self._state, self._trial = BreakerState.CLOSED, False
        self.failures = 0

    def record_failure(self, code: str) -> None:
        self.failures += 1
        self.last_error = code
        if self._state is BreakerState.HALF_OPEN or self.failures >= self.threshold:
            self._state, self._opened_at = BreakerState.OPEN, self._clock()
        self._trial = False

    def release(self) -> None:
        """The call ended without a verdict (e.g. cancelled): free the trial slot."""
        self._trial = False
