"""Read-only endpoint for concise Runtime state."""

from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict

router = APIRouter(prefix="/api/v1", tags=["engine"])


class EngineStateResponse(BaseModel):
    """Runtime state that intentionally excludes the full Experience/game state."""

    model_config = ConfigDict(extra="forbid")

    runtime: Literal["running", "stopped", "failed"]
    active_experience: str | None
    experience_status: Literal["stopped", "starting", "running", "stopping", "failed"]


@router.get("/engine/state", response_model=EngineStateResponse, summary="Engine Runtime state")
def get_engine_state(request: Request) -> dict[str, str | None]:
    return request.app.state.engine_runtime.state()
