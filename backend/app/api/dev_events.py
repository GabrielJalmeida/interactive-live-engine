"""Development/test-only HTTP endpoint for simulating normalized live events."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Request
from pydantic import Field, JsonValue, field_validator, model_validator

from backend.app.application.event_ingestion import EventIngestionResult
from backend.app.domain.events import (
    DomainContract,
    EventProvider,
    EventType,
    LiveEvent,
    Viewer,
    utc_now,
    validate_json_object_limits,
)

router = APIRouter(prefix="/api/v1/dev", tags=["development"])


class DevEventRequest(DomainContract):
    """Client-controlled simulation fields; provider and internal IDs remain server-owned."""

    type: EventType
    provider_event_id: str | None = Field(default=None, min_length=1, max_length=256)
    session_id: str | None = Field(default=None, min_length=1, max_length=256)
    occurred_at: datetime | None = None
    viewer: Viewer | None = None
    payload: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator("occurred_at")
    @classmethod
    def occurred_at_must_be_aware(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp must include a timezone")
        return value

    @field_validator("payload")
    @classmethod
    def payload_must_obey_json_limits(cls, value: dict[str, JsonValue]) -> dict[str, JsonValue]:
        validate_json_object_limits(value)
        return value

    @model_validator(mode="after")
    def validate_known_payload_fields(self) -> DevEventRequest:
        # These are validation rules for the simulator's common event fields only;
        # arbitrary extra JSON keys remain Experience-owned and are not interpreted here.
        if self.type is EventType.COMMENT:
            text = self.payload.get("text")
            if not isinstance(text, str):
                raise ValueError("COMMENT payload must include a text string")
            if len(text) > 4000:
                raise ValueError("COMMENT text must not exceed 4000 characters")

        if "quantity" in self.payload:
            quantity = self.payload["quantity"]
            if type(quantity) is not int or not 1 <= quantity <= 10_000:
                raise ValueError("quantity must be an integer between 1 and 10000")

        if self.type is EventType.LIKE and "count" in self.payload:
            count = self.payload["count"]
            if type(count) is not int or not 1 <= count <= 1_000_000:
                raise ValueError("LIKE count must be an integer between 1 and 1000000")

        return self

    def to_live_event(self) -> LiveEvent:
        """Build the internal contract with origin and internal metadata set server-side."""

        return LiveEvent(
            type=self.type,
            provider=EventProvider.SIMULATOR,
            provider_event_id=self.provider_event_id,
            session_id=self.session_id,
            occurred_at=self.occurred_at or utc_now(),
            viewer=self.viewer,
            payload=self.payload,
        )


@router.post("/events", response_model=EventIngestionResult, summary="Simulate a live event")
async def simulate_event(
    body: DevEventRequest,
    request: Request,
) -> EventIngestionResult:
    """Feed one simulated event through the same ingestion service used by providers."""

    ingestion_service = request.app.state.event_ingestion_service
    return await ingestion_service.ingest(body.to_live_event())
