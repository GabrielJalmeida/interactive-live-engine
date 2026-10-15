"""Validated, provider-independent event contracts for the Interactive Live Engine."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID, uuid4

from pydantic import (
    AnyHttpUrl,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StringConstraints,
    field_validator,
    model_validator,
)

MAX_JSON_OBJECT_BYTES = 16 * 1024
MAX_JSON_NESTING_DEPTH = 8


class EventType(StrEnum):
    """Event types normalized by the provider boundary."""

    COMMENT = "COMMENT"
    GIFT = "GIFT"
    LIKE = "LIKE"
    FOLLOW = "FOLLOW"
    SHARE = "SHARE"
    JOIN = "JOIN"
    CONNECT = "CONNECT"
    DISCONNECT = "DISCONNECT"


class EventProvider(StrEnum):
    """Provider identifiers controlled by the Engine, not by external payloads."""

    TIKTOK = "tiktok"
    SIMULATOR = "simulator"


ExperienceSlug = Annotated[
    str,
    StringConstraints(
        min_length=1,
        max_length=80,
        pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
    ),
]

OutputType = Annotated[
    str,
    StringConstraints(
        min_length=2,
        max_length=64,
        pattern=r"^[A-Z][A-Z0-9_]*$",
    ),
]


def utc_now() -> datetime:
    """Return an aware UTC timestamp."""

    return datetime.now(UTC)


def _normalize_utc(value: datetime) -> datetime:
    """Reject naive timestamps and normalize aware ones to UTC."""

    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must include a timezone")
    return value.astimezone(UTC)


def _json_depth(value: JsonValue) -> int:
    """Return maximum nesting depth, counting the top-level object as depth one."""

    if isinstance(value, dict):
        return 1 + max((_json_depth(item) for item in value.values()), default=0)
    if isinstance(value, list):
        return 1 + max((_json_depth(item) for item in value), default=0)
    return 0


def validate_json_object_limits(value: dict[str, JsonValue]) -> None:
    """Enforce consistent encoded-size and nesting limits for JSON object fields."""

    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, RecursionError) as exc:
        raise ValueError("value must be a valid JSON object") from exc

    if len(encoded) > MAX_JSON_OBJECT_BYTES:
        raise ValueError(f"JSON object exceeds the {MAX_JSON_OBJECT_BYTES}-byte limit")
    if _json_depth(value) > MAX_JSON_NESTING_DEPTH:
        raise ValueError(f"JSON object exceeds the nesting-depth limit of {MAX_JSON_NESTING_DEPTH}")


class DomainContract(BaseModel):
    """Shared strict behavior for public domain contracts."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
        validate_default=True,
        allow_inf_nan=False,
    )


class Viewer(DomainContract):
    """Normalized viewer identity; fields are optional because provider data varies."""

    provider_user_id: str | None = Field(default=None, min_length=1, max_length=128)
    username: str | None = Field(default=None, min_length=1, max_length=128)
    display_name: str | None = Field(default=None, min_length=1, max_length=128)
    avatar_url: AnyHttpUrl | None = None

    @model_validator(mode="after")
    def require_some_identity(self) -> Viewer:
        if not any((self.provider_user_id, self.username, self.display_name, self.avatar_url)):
            raise ValueError("viewer must contain at least one identity or presentation field")
        return self


class LiveEvent(DomainContract):
    """Internal normalized event; contains no provider SDK or gameplay-specific objects."""

    event_id: UUID = Field(default_factory=uuid4)
    type: EventType
    provider: EventProvider
    provider_event_id: str | None = Field(default=None, min_length=1, max_length=256)
    session_id: str | None = Field(default=None, min_length=1, max_length=256)
    occurred_at: datetime
    received_at: datetime = Field(default_factory=utc_now)
    viewer: Viewer | None = None
    payload: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator("occurred_at", "received_at")
    @classmethod
    def timestamps_must_be_aware_utc(cls, value: datetime) -> datetime:
        return _normalize_utc(value)

    @model_validator(mode="after")
    def validate_payload_limits(self) -> LiveEvent:
        validate_json_object_limits(self.payload)
        return self


class OutputEvent(DomainContract):
    """Versioned output envelope transported to clients without gameplay interpretation."""

    protocol_version: Literal[1] = 1
    message_id: UUID = Field(default_factory=uuid4)
    type: OutputType
    experience: ExperienceSlug
    occurred_at: datetime = Field(default_factory=utc_now)
    data: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator("occurred_at")
    @classmethod
    def timestamp_must_be_aware_utc(cls, value: datetime) -> datetime:
        return _normalize_utc(value)

    @model_validator(mode="after")
    def validate_data_limits(self) -> OutputEvent:
        validate_json_object_limits(self.data)
        return self
