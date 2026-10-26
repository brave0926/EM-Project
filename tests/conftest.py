import httpx
import pytest_asyncio

from backend.app.clients.mcp_client import McpClient, set_mcp_client
from backend.app.main import app
from mcp_server.providers import MockProvider
from mcp_server.server import build_server


@pytest_asyncio.fixture
async def api():
    """Factory: api(**MockProvider kwargs, timeout_s=..., server=...) -> httpx client for the app,
    with the app-wide MCP client pointed at an in-process em-mcp-server."""
    clients: list[McpClient] = []

    def make(timeout_s: float = 2.0, server=None, **provider_kwargs):
        if server is None:
            server = build_server(MockProvider(**({"delay_ms_range": (0, 0), "seed": 1} | provider_kwargs)))
        mcp = McpClient(server, timeout_s=timeout_s)
        clients.append(mcp)
        set_mcp_client(mcp)
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")

    yield make
    for mcp in clients:
        await mcp.aclose()
    set_mcp_client(None)
