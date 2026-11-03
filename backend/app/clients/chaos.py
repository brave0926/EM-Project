"""Demo chaos state: the active failure-injection rule per tool. In memory, no I/O, no FastAPI.

Lives in clients (next to the MCP client that applies it) and imports only core and models, so
mcp_client can read it and services/chaos_service can write it without an import cycle.
Every rule expires on its own (store clock), so a forgotten switch cannot break the app.
"""

from __future__ import annotations

from collections.abc import Callable
from time import monotonic

from backend.app.models.chaos import CHAOS_TOOLS, ChaosRule, ChaosTool


class ChaosStore:
    def __init__(self, clock: Callable[[], float] = monotonic) -> None:
        self.clock = clock
        self._rules: dict[str, ChaosRule] = {}

    def set(self, tool: ChaosTool, rule: ChaosRule | None) -> None:
        if rule is None:
            self._rules.pop(tool, None)
        else:
            self._rules[tool] = rule

    def rule(self, tool: str) -> ChaosRule | None:
        """The live rule for a tool; an expired one is dropped here."""
        rule = self._rules.get(tool)
        if rule is not None and self.clock() >= rule.expires_at:
            del self._rules[tool]
            return None
        return rule

    def any_active(self) -> bool:
        return any(self.rule(tool) is not None for tool in CHAOS_TOOLS)

    def clear(self) -> None:
        self._rules.clear()


_store = ChaosStore()


def get_chaos_store() -> ChaosStore:
    return _store


def set_chaos_store(store: ChaosStore | None) -> None:
    """Install a store (tests pass a fake clock); None puts back a fresh one."""
    global _store
    _store = store or ChaosStore()
