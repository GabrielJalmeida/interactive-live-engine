"""SQLAlchemy models for infrastructure event records and durable deduplication keys."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Uuid,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator


class Base(DeclarativeBase):
    """Declarative base for the Engine's infrastructure schema."""


class UTCDateTime(TypeDecorator[datetime]):
    """Store UTC timestamps and restore timezone awareness when SQLite drops tzinfo."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("database timestamps must include a timezone")
        normalized = value.astimezone(UTC)
        if dialect.name == "sqlite":
            return normalized.replace(tzinfo=None)
        return normalized

    def process_result_value(self, value: datetime | None, _dialect: Any) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


class LiveEventRecord(Base):
    """Immutable event receipt plus mutable infrastructure processing metadata."""

    __tablename__ = "live_event_records"
    __table_args__ = (
        CheckConstraint(
            "processing_status IN ('RECEIVED', 'PROCESSED', 'FAILED')",
            name="ck_live_event_records_processing_status",
        ),
        Index("ix_live_event_records_received_at", "received_at"),
        Index("ix_live_event_records_processing_status", "processing_status"),
        Index("ix_live_event_records_session_id", "session_id"),
    )

    event_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_event_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    session_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    received_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    viewer_data: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    processing_status: Mapped[str] = mapped_column(String(16), nullable=False, default="RECEIVED")
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    processed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)


class EventDeduplicationKey(Base):
    """Durable claim for an external event identity, separate from event history."""

    __tablename__ = "event_deduplication_keys"

    provider: Mapped[str] = mapped_column(String(32), primary_key=True)
    provider_event_id: Mapped[str] = mapped_column(String(256), primary_key=True)
    event_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("live_event_records.event_id", ondelete="CASCADE"),
        nullable=False,
    )

    __table_args__ = (Index("ix_event_deduplication_keys_event_id", "event_id", unique=True),)
