"""MCP client: the backend's only path to facility data. No FastAPI, no mcp_server imports.

The connection opens lazily on the first call and lives in a background task it owns
(anyio requires the same task to open and close it). A dropped connection is reopened
once per call. One RT-102 deadline (timeout_s) covers connect, call and reconnect. Usage:
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
CLOSE_GRACE_S = 1.0  # time allowed for a clean close before cancelling
ErrorCode = Literal["UNAVAILABLE", "TIMEOUT", "TOOL_ERROR", "BAD_RESPONSE"]

_ERS = TypeAdapter(list[ERFacility])
_PHARMACIES = TypeAdapter(list[PharmacyFacility])
_ITEMS = TypeAdapter(list[str])


class McpClientError(Exception):
    """Any failure reaching or using em-mcp-server. The v1.0 fallback hooks in here."""

    def __init__(self, code: ErrorCode, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.connection: asyncio.Task[None] | None = None  # the connection that failed, if any


def _tag(exc: BaseException, connection: asyncio.Task[None]) -> BaseException:
    if isinstance(exc, McpClientError):
        exc.connection = connection
    return exc


class McpClient:
    def __init__(self, server: Any = None, timeout_s: float = TOOL_TIMEOUT_S) -> None:
        """server: URL (default settings.mcp_url) or, in tests, an in-process MCP server."""
        self._server = server or settings.mcp_url
        self.timeout_s = timeout_s
        self._client: Client | None = None
        self._owner: asyncio.Task[None] | None = None
        self._ready: asyncio.Future[None] | None = None
        self._stop = asyncio.Event()
        self._lock = asyncio.Lock()

    async def __aenter__(self) -> McpClient:
        await self.connect()
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    async def connect(self, timeout_s: float | None = None) -> asyncio.Task[None]:
        """Open the connection if needed and return it. Concurrent callers share one handshake."""
        timeout_s = self.timeout_s if timeout_s is None else timeout_s
        async with self._lock:
            if self._owner is None or self._owner.done():
                self._stop = asyncio.Event()
                self._ready = asyncio.get_running_loop().create_future()
                # mark a failure as retrieved even if no caller is left waiting
                self._ready.add_done_callback(lambda f: f.cancelled() or f.exception())
                self._owner = asyncio.create_task(self._hold(self._ready))
            owner, ready = self._owner, self._ready
        done, _ = await asyncio.wait({ready}, timeout=timeout_s)  # never cancels the shared handshake
        if not done:
            await self._close(owner)  # abandon a handshake that never finishes
            raise McpClientError("TIMEOUT", f"no handshake from em-mcp-server within {timeout_s:.2f} s")
        if (exc := ready.exception()) is not None:
            raise _tag(exc, owner)
        return owner

    async def aclose(self) -> None:
        await self._close(self._owner)

    async def _close(self, owner: asyncio.Task[None] | None) -> None:
        """Close `owner` only if it is still the current connection, never a newer one."""
        if owner is None or owner is not self._owner:
            return
        self._owner = None
        self._stop.set()
        handshake_done = self._ready is not None and self._ready.done()
        done, _ = await asyncio.wait({owner}, timeout=CLOSE_GRACE_S if handshake_done else 0)
        if not done:  # stuck in the handshake or in close: cancel it
            owner.cancel()
            await asyncio.gather(owner, return_exceptions=True)

    async def _hold(self, ready: asyncio.Future[None]) -> None:
        client: Client | None = None
        stop = self._stop  # this connection's own stop signal
        try:
            async with Client(self._server) as client:
                self._client = client
                if not ready.done():
                    ready.set_result(None)
                await stop.wait()
        except Exception as exc:
            if not ready.done():
                ready.set_exception(
                    McpClientError("UNAVAILABLE", f"cannot connect to em-mcp-server: {exc!r}")
                )
        finally:
            if client is not None and self._client is client:  # don't clear a newer connection
                self._client = None
            if not ready.done():  # cancelled before the handshake finished
                ready.set_exception(McpClientError("UNAVAILABLE", "connection closed during handshake"))

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
        # One RT-102 budget covers connect, the call and the single reconnect.
        deadline = asyncio.get_running_loop().time() + self.timeout_s
        try:
            return await self._call_once(tool, args, adapter, deadline)
        except McpClientError as exc:
            if exc.code != "UNAVAILABLE":
                raise
            # Connection dropped: close the one this call used (a parallel call may already
            # have opened a newer one), then try once more.
            await self._close(exc.connection)
        return await self._call_once(tool, args, adapter, deadline)

    def _remaining(self, tool: str, deadline: float) -> float:
        left = deadline - asyncio.get_running_loop().time()
        if left <= 0:
            raise McpClientError("TIMEOUT", f"{tool}: no answer within {self.timeout_s:.2f} s")
        return left

    async def _call_once(self, tool: str, args: dict[str, Any], adapter: TypeAdapter[T], deadline: float) -> T:
        owner = await self.connect(self._remaining(tool, deadline))
        client = self._client
        if client is None:
            raise _tag(McpClientError("UNAVAILABLE", f"{tool}: connection closed"), owner)
        try:
            result = await client.call_tool(tool, args, read_timeout_seconds=self._remaining(tool, deadline))
        except MCPError as exc:
            code: ErrorCode = "TIMEOUT" if "Timed out" in str(exc) else "UNAVAILABLE"
            raise _tag(McpClientError(code, f"{tool}: {exc}"), owner) from exc
        except Exception as exc:
            raise _tag(McpClientError("UNAVAILABLE", f"{tool}: {exc!r}"), owner) from exc
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
