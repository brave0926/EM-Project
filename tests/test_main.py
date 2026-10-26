import json

import pytest

from backend.app.clients.mcp_client import McpClientError
from backend.app.main import MCP_ERROR_STATUS, mcp_error_handler


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("code", "status"),
    [("UNAVAILABLE", 503), ("TIMEOUT", 504), ("TOOL_ERROR", 502), ("BAD_RESPONSE", 502)],
)
async def test_mcp_errors_map_to_http(code, status):
    resp = await mcp_error_handler(None, McpClientError(code, "boom"))
    assert resp.status_code == status
    assert json.loads(resp.body) == {"error": code, "detail": f"{code}: boom"}


def test_every_error_code_is_mapped():
    assert set(MCP_ERROR_STATUS) == {"UNAVAILABLE", "TIMEOUT", "TOOL_ERROR", "BAD_RESPONSE"}
