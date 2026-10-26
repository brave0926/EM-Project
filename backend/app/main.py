"""Composition root: builds the app, owns the shared MCP client, maps client errors to HTTP."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from backend.app.clients.mcp_client import McpClientError, get_mcp_client
from backend.app.controllers import facilities_er_controller, facilities_pharmacy_controller, health_controller
from backend.app.core.config import settings

MCP_ERROR_STATUS = {"UNAVAILABLE": 503, "TIMEOUT": 504, "TOOL_ERROR": 502, "BAD_RESPONSE": 502}


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield  # the MCP client connects lazily on first use, so the app starts even if MCP is down
    await get_mcp_client().aclose()


async def mcp_error_handler(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, McpClientError)
    return JSONResponse(status_code=MCP_ERROR_STATUS[exc.code], content={"error": exc.code, "detail": str(exc)})


app = FastAPI(title=settings.title, description=settings.description, version=settings.version, lifespan=lifespan)
app.add_exception_handler(McpClientError, mcp_error_handler)
app.include_router(health_controller.router, tags=["Health"])
app.include_router(facilities_er_controller.router, tags=["Facilities"])
app.include_router(facilities_pharmacy_controller.router, tags=["Facilities"])
