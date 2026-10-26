from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from backend.app.schemas.er_facility import ERFacilitiesQuery, ERFacilitiesResponse
from backend.app.services import er_facility_service

router = APIRouter()


@router.get("/facilities/er", response_model=ERFacilitiesResponse)
async def list_ers(query: Annotated[ERFacilitiesQuery, Query()]) -> ERFacilitiesResponse:
    ers = await er_facility_service.find_ers(query.region, query.lat, query.lon, query.available_only)
    return ERFacilitiesResponse(facilities=ers)
