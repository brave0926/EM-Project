from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from backend.app.schemas.pharmacy_facility import PharmacyFacilitiesQuery, PharmacyFacilitiesResponse
from backend.app.services import pharmacy_facility_service

router = APIRouter()


@router.get("/facilities/ph", response_model=PharmacyFacilitiesResponse)
async def list_pharmacies(query: Annotated[PharmacyFacilitiesQuery, Query()]) -> PharmacyFacilitiesResponse:
    at_time, pharmacies, notices = await pharmacy_facility_service.find_open_pharmacies(
        query.lat, query.lon, query.at_time
    )
    return PharmacyFacilitiesResponse(at_time=at_time, facilities=pharmacies, notices=notices)
