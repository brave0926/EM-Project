from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from backend.app.schemas.chaos import ChaosRequestSchema, ChaosStateSchema
from backend.app.services import chaos_service


def _require_enabled() -> None:
    """The endpoints exist only with EM_DEMO_CHAOS=1; otherwise they are a plain 404."""
    if not chaos_service.enabled():
        raise HTTPException(status_code=404, detail="Not Found")


router = APIRouter(prefix="/demo/chaos", dependencies=[Depends(_require_enabled)])


@router.post("", response_model=ChaosStateSchema)
async def set_chaos(request: ChaosRequestSchema) -> ChaosStateSchema:
    """Demo only: inject failures or delays into the ER / pharmacy tool calls. Expires on its own."""
    state = chaos_service.set_chaos(request.target, request.mode, request.delay_ms, request.duration_s)
    return ChaosStateSchema.model_validate(state.model_dump())


@router.get("", response_model=ChaosStateSchema)
async def get_chaos() -> ChaosStateSchema:
    """Demo only: current failure injection and seconds left."""
    return ChaosStateSchema.model_validate(chaos_service.get_state().model_dump())


@router.delete("", response_model=ChaosStateSchema)
async def reset_chaos() -> ChaosStateSchema:
    """Demo only: turn all failure injection off (open breakers recover via HALF_OPEN as usual)."""
    return ChaosStateSchema.model_validate(chaos_service.reset().model_dump())
