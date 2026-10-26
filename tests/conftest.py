import asyncio

import httpx
import pytest_asyncio

from backend.app.clients.mcp_client import McpClient, set_mcp_client
from backend.app.main import app
from mcp_server.providers import MockProvider
from mcp_server.server import build_server


@pytest_asyncio.fixture
async def use_mcp():
    """Factory: use_mcp(**MockProvider kwargs, timeout_s=..., server=...) points the app-wide
    MCP client at an in-process em-mcp-server (or the given server/URL)."""
    clients: list[McpClient] = []

    def make(timeout_s: float = 2.0, server=None, **provider_kwargs) -> McpClient:
        if server is None:
            server = build_server(MockProvider(**({"delay_ms_range": (0, 0), "seed": 1} | provider_kwargs)))
        mcp = McpClient(server, timeout_s=timeout_s)
        clients.append(mcp)
        set_mcp_client(mcp)
        return mcp

    yield make
    for mcp in clients:
        await mcp.aclose()
    set_mcp_client(None)


@pytest_asyncio.fixture
async def api(use_mcp):
    """Factory: same arguments as use_mcp -> httpx client for the app."""

    def make(**kwargs):
        use_mcp(**kwargs)
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")

    return make


@pytest_asyncio.fixture
async def silent_server_url():
    """URL of a TCP server that accepts connections but never answers (hung em-mcp-server)."""

    async def never_answer(reader, writer):
        await asyncio.sleep(3600)

    server = await asyncio.start_server(never_answer, "127.0.0.1", 0)
    yield f"http://127.0.0.1:{server.sockets[0].getsockname()[1]}/mcp"
    server.close()
