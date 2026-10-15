"""Protocol messages owned by the Engine's realtime transport."""

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.app.domain.events import utc_now


class SystemReadyMessage(BaseModel):
    """Initial control message sent after a WebSocket connection is accepted."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    protocol_version: Literal[1] = 1
    type: Literal["SYSTEM_READY"] = "SYSTEM_READY"
    occurred_at: datetime = Field(default_factory=utc_now)

    @field_validator("occurred_at")
    @classmethod
    def timestamp_must_be_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp must include a timezone")
        return value.astimezone(UTC)
