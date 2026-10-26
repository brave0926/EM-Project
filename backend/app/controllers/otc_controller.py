from __future__ import annotations

from fastapi import APIRouter

from backend.app.models.enums import Category
from backend.app.schemas.otc import OtcResponse
from backend.app.services import otc_service

router = APIRouter()


@router.get("/otc/{cat}", response_model=OtcResponse)
async def get_otc(cat: Category) -> OtcResponse:
    advice = await otc_service.get_otc_advice(cat)
    return OtcResponse(category=advice.category, items=advice.items, call_119=advice.call_119)
