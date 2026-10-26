from __future__ import annotations

from fastapi import FastAPI

from backend.app.controllers import health_controller
from backend.app.core.config import settings

app = FastAPI(title=settings.title, description=settings.description, version=settings.version)
app.include_router(health_controller.router, tags=["Health"])
