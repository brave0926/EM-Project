"""MCP client: the backend's only path to facility data. No FastAPI, no mcp_server imports.

The connection opens lazily on the first call and lives in a background task it owns
(anyio requires the same task to open and close it). A dropped connection is reopened
once per call. Usage:
    async with McpClient() as mcp:          # or: mcp = McpClient(); ...; await mcp.aclose()
        ers = await mcp.get_er_beds("Chungju", near=loc)
"""

from __future__ import annotations

import asyncio
from typing import Any, Literal, TypeVar

from mcp import Client, MCPError
from pydantic import TypeAdapter, ValidationError

from backend.app.core.config import TOOL_TIMEOUT_S, settings
from backend.app.models.domain import ERFacility, Location, PharmacyFacility
from backend.app.models.enums import Category

T = TypeVar("T")
ErrorCode = Literal["UNAVAILABLE", "TIMEOUT", "TOOL_ERROR", "BAD_RESPONSE"]

_ERS = TypeAdapter(list[ERFacility])
_PHARMACIES = TypeAdapter(list[PharmacyFacility])
_ITEMS = TypeAdapter(list[str])


class McpClientError(Exception):
    """Any failure reaching or using em-mcp-server. The v1.0 fallback hooks in here."""

    def __init__(self, code: ErrorCode, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


class McpClient:
    def __init__(self, server: Any = None, timeout_s: float = TOOL_TIMEOUT_S) -> None:
        """server: URL (default settings.mcp_url) or, in tests, an in-process MCP server."""
        self._server = server or settings.mcp_url
        self.timeout_s = timeout_s
        self._client: Client | None = None
        self._owner: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()
        self._lock = asyncio.Lock()

    async def __aenter__(self) -> McpClient:
        await self.connect()
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    async def connect(self) -> None:
        async with self._lock:
            if self._owner is not None and not self._owner.done():
                return
            self._stop = asyncio.Event()
            ready: asyncio.Future[None] = asyncio.get_running_loop().create_future()
            self._owner = asyncio.create_task(self._hold(ready))
            await ready

    async def aclose(self) -> None:
        self._stop.set()
        if self._owner is not None:
            await asyncio.gather(self._owner, return_exceptions=True)
        self._owner = None

    async def _hold(self, ready: asyncio.Future[None]) -> None:
        try:
            async with Client(self._server) as client:
                self._client = client
                ready.set_result(None)
                await self._stop.wait()
        except Exception as exc:
            if not ready.done():
                ready.set_exception(
                    McpClientError("UNAVAILABLE", f"cannot connect to em-mcp-server: {exc!r}")
                )
        finally:
            self._client = None

    async def get_er_beds(self, region: str, near: Location | None = None) -> list[ERFacility]:
        args: dict[str, Any] = {"region": region}
        if near:
            args |= {"lat": near.lat, "lon": near.lon}
        return await self._call("get_er_beds", args, _ERS)

    async def get_pharmacies(self, near: Location, at_time: str | None = None) -> list[PharmacyFacility]:
        args: dict[str, Any] = {"lat": near.lat, "lon": near.lon}
        if at_time:
            args["at_time"] = at_time
        return await self._call("get_pharmacies", args, _PHARMACIES)

    async def get_otc(self, category: Category) -> list[str]:
        return await self._call("get_otc", {"category": category.value}, _ITEMS)

    async def _call(self, tool: str, args: dict[str, Any], adapter: TypeAdapter[T]) -> T:
        try:
            return await self._call_once(tool, args, adapter)
        except McpClientError as exc:
            if exc.code != "UNAVAILABLE":
                raise
        await self.aclose()  # connection dropped: reopen once, then give up
        return await self._call_once(tool, args, adapter)

    async def _call_once(self, tool: str, args: dict[str, Any], adapter: TypeAdapter[T]) -> T:
        await self.connect()
        if self._client is None:
            raise McpClientError("UNAVAILABLE", f"{tool}: connection closed")
        try:
            result = await self._client.call_tool(tool, args, read_timeout_seconds=self.timeout_s)
        except MCPError as exc:
            code: ErrorCode = "TIMEOUT" if "Timed out" in str(exc) else "UNAVAILABLE"
            raise McpClientError(code, f"{tool}: {exc}") from exc
        except Exception as exc:
            raise McpClientError("UNAVAILABLE", f"{tool}: {exc!r}") from exc
        if result.is_error:
            text = " ".join(getattr(c, "text", "") for c in result.content)
            raise McpClientError("TOOL_ERROR", f"{tool}: {text}")
        try:
            return adapter.validate_python((result.structured_content or {})["result"])
        except (KeyError, ValidationError) as exc:
            raise McpClientError("BAD_RESPONSE", f"{tool}: {exc}") from exc


_shared: McpClient | None = None


def get_mcp_client() -> McpClient:
    """App-wide client (lazy). main.py closes it on shutdown."""
    global _shared
    if _shared is None:
        _shared = McpClient()
    return _shared


def set_mcp_client(client: McpClient | None) -> None:
    """Swap the app-wide client (tests use an in-process server)."""
    global _shared
    _shared = client
