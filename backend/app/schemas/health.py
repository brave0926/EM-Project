from __future__ import annotations

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str = Field(description="'ok' when the service is up.")
    version: str = Field(description="API version.")
