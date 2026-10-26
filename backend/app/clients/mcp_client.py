"""MCP client: the backend's only path to facility data. No FastAPI, no mcp_server imports.

Usage:
    async with McpClient() as mcp:
        ers = await mcp.get_er_beds("Chungju", near=loc)
"""

from __future__ import annotations

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
        self._client = Client(server or settings.mcp_url)
        self.timeout_s = timeout_s

    async def __aenter__(self) -> McpClient:
        try:
            await self._client.__aenter__()
        except Exception as exc:
            raise McpClientError("UNAVAILABLE", f"cannot connect to em-mcp-server: {exc!r}") from exc
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self._client.__aexit__(*exc_info)

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
