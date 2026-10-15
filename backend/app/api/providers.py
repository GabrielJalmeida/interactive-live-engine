"""Provider-neutral operational status endpoints."""

from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field

router = APIRouter(prefix="/api/v1/providers", tags=["providers"])


class TikTokProviderStatusResponse(BaseModel):
    """Safe status for the TikTok adapter; no username, payload, or SDK object is exposed."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: Literal["tiktok"] = "tiktok"
    enabled: bool
    status: Literal[
        "disabled", "stopped", "starting", "connected", "disconnected", "stopping", "failed"
    ]
    provider_events_received: int = Field(ge=0)
    normalized_events: int = Field(ge=0)
    processed_events: int = Field(ge=0)
    duplicate_events: int = Field(ge=0)
    failed_events: int = Field(ge=0)
    ignored_gift_updates: int = Field(ge=0)
    last_event_at: str | None = None
    last_error_code: str | None = None


@router.get(
    "/tiktok", response_model=TikTokProviderStatusResponse, summary="TikTok provider status"
)
def get_tiktok_provider_status(request: Request) -> TikTokProviderStatusResponse:
    """Return only operational counters; event text and user data are never included."""

    adapter = request.app.state.tiktok_live_adapter
    return TikTokProviderStatusResponse(**adapter.snapshot())
