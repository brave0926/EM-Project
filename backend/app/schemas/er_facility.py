"""API DTOs for GET /facilities/er."""

from __future__ import annotations

from pydantic import BaseModel, Field, computed_field, model_validator

from backend.app.models.domain import ERFacility
from backend.app.models.enums import DataStatus


class ERFacilitiesQuery(BaseModel):
    region: str = Field(default="Chungju", min_length=1, description="Region to search.")
    lat: float | None = Field(default=None, ge=-90, le=90, description="User latitude (with lon).")
    lon: float | None = Field(default=None, ge=-180, le=180, description="User longitude (with lat).")
    available_only: bool = Field(default=False, description="Drop ERs with no free beds (hvec = 0).")

    @model_validator(mode="after")
    def _lat_lon_together(self) -> ERFacilitiesQuery:
        if (self.lat is None) != (self.lon is None):
            raise ValueError("lat and lon must be given together")
        return self


class ERFacilitiesResponse(BaseModel):
    facilities: list[ERFacility] = Field(
        description="ERs with free beds first, then nearest first when lat/lon given."
    )

    @computed_field(description="Number of facilities returned.")
    @property
    def count(self) -> int:
        return len(self.facilities)

    @computed_field(description="True if any item is UNCERTAIN (data older than 180 min, RT-104).")
    @property
    def any_uncertain(self) -> bool:
        return any(f.status is DataStatus.UNCERTAIN for f in self.facilities)
