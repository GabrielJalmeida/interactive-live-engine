"""Health endpoint for the initial bootstrap slice."""

from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel

router = APIRouter(prefix="/api/v1", tags=["system"])


class HealthResponse(BaseModel):
    """Liveness response; does not yet claim provider or database readiness."""

    status: Literal["ok"]
    service: Literal["interactive-live-engine"]
    environment: Literal["development", "test", "production"]


@router.get("/health", response_model=HealthResponse, summary="Application health")
def get_health(request: Request) -> HealthResponse:
    """Report that the HTTP application is responding."""

    settings = request.app.state.settings
    return HealthResponse(
        status="ok",
        service="interactive-live-engine",
        environment=settings.app_env,
    )
