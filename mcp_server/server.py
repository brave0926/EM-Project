"""em-mcp-server: exposes the data provider as MCP tools over streamable HTTP.

Run: python -m mcp_server.server   (EM_MCP_HOST / EM_MCP_PORT, default 127.0.0.1:8001)
Reads .env at start; EM_PROVIDER=mock (default) or live.
"""

from __future__ import annotations

import os
from collections.abc import Awaitable
from typing import TypeVar

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from backend.app.core.env import load_env
from backend.app.models.domain import ERFacility, Location, PharmacyFacility
from backend.app.models.enums import Category
from mcp_server.providers import DataProvider, ProviderError, get_provider

SERVER_NAME = "em-mcp-server"

T = TypeVar("T")


async def _guard(call: Awaitable[T]) -> T:
    """Map provider failures to MCP tool errors with a stable code prefix."""
    try:
        return await call
    except ProviderError as exc:
        raise ToolError(f"PROVIDER_ERROR: {exc}") from exc
    except NotImplementedError as exc:
        raise ToolError(f"NOT_IMPLEMENTED: {exc}") from exc


def build_server(provider: DataProvider | None = None) -> MCPServer:
    provider = provider or get_provider()
    server = MCPServer(SERVER_NAME, instructions="Emergency facility data, labelled MOCK or LIVE.")

    @server.tool(description="ERs in a region with free beds (hvec); nearest first when lat/lon given.")
    async def get_er_beds(
        region: str, lat: float | None = None, lon: float | None = None
    ) -> list[ERFacility]:
        near = Location(name="query point", lat=lat, lon=lon) if lat is not None and lon is not None else None
        return await _guard(provider.get_er_beds(region, near))

    @server.tool(description="Pharmacies open at at_time (HH:MM, default now in KST), nearest first.")
    async def get_pharmacies(lat: float, lon: float, at_time: str | None = None) -> list[PharmacyFacility]:
        near = Location(name="query point", lat=lat, lon=lon)
        return await _guard(provider.get_pharmacies(near, at_time))

    @server.tool(description="Generic first-aid items for a category. Empty for critical: call 119.")
    async def get_otc(category: Category) -> list[str]:
        return await _guard(provider.get_otc(category))

    return server


def main() -> None:
    load_env()  # .env: EM_PROVIDER and the data.go.kr keys; the shell environment wins
    host = os.environ.get("EM_MCP_HOST", "127.0.0.1")
    port = int(os.environ.get("EM_MCP_PORT", "8001"))
    build_server().run("streamable-http", host=host, port=port)


if __name__ == "__main__":
    main()
