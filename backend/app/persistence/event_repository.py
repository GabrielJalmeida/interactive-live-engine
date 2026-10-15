"""SQLAlchemy adapter for event history, lifecycle status, and durable deduplication."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from backend.app.application.event_ingestion import EventDeduplicationPort
from backend.app.domain.events import LiveEvent
from backend.app.persistence.models import EventDeduplicationKey, LiveEventRecord


class EventRepositoryError(RuntimeError):
    """Raised when an infrastructure event record cannot be updated consistently."""


class SqlAlchemyEventStore(EventDeduplicationPort):
    """Persistent event store implementing ingestion reservation/status operations.

    Each database operation gets its own Session inside a worker thread. Sessions are
    never shared by concurrent async requests. A separate unique-key table allows failed
    attempts to remain in the event history while releasing their dedupe claim for retry.
    """

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    async def reserve(self, event: LiveEvent) -> UUID | None:
        """Persist an event and atomically claim an eligible provider ID."""

        return await asyncio.to_thread(self._reserve_sync, event)

    async def mark_processed(self, event: LiveEvent) -> None:
        """Persist successful Experience processing before output publication."""

        await asyncio.to_thread(self._mark_processed_sync, event.event_id)

    async def release(self, event: LiveEvent) -> None:
        """Mark a failed dispatch and release only the dedupe claim owned by that event."""

        await asyncio.to_thread(self._release_sync, event)

    async def get_record(self, event_id: UUID) -> dict[str, Any] | None:
        """Return a detached diagnostic snapshot for tests/tools, excluding viewer payloads."""

        return await asyncio.to_thread(self._get_record_sync, event_id)

    async def count_records(self) -> int:
        """Return the number of retained event records; primarily useful for verification."""

        return await asyncio.to_thread(self._count_records_sync)

    async def purge_expired_before(self, cutoff: datetime) -> int:
        """Delete event history older than an explicit UTC cutoff, including dedupe keys."""

        if cutoff.tzinfo is None or cutoff.utcoffset() is None:
            raise ValueError("retention cutoff must include a timezone")
        return await asyncio.to_thread(self._purge_expired_sync, cutoff.astimezone(UTC))

    def _reserve_sync(self, event: LiveEvent) -> UUID | None:
        try:
            with self._session_factory.begin() as session:
                session.add(self._build_record(event))
                session.flush()
                if event.provider_event_id is not None:
                    session.add(
                        EventDeduplicationKey(
                            provider=event.provider.value,
                            provider_event_id=event.provider_event_id,
                            event_id=event.event_id,
                        )
                    )
            return None
        except IntegrityError:
            # A uniqueness collision means a concurrent request already claimed this
            # provider identity (or the exact internal event ID was submitted twice).
            with self._session_factory() as session:
                if event.provider_event_id is not None:
                    key = session.get(
                        EventDeduplicationKey,
                        (event.provider.value, event.provider_event_id),
                    )
                    if key is not None:
                        return key.event_id
                existing = session.get(LiveEventRecord, event.event_id)
                if existing is not None:
                    return existing.event_id
            raise

    @staticmethod
    def _build_record(event: LiveEvent) -> LiveEventRecord:
        viewer_data = None
        if event.viewer is not None:
            viewer_data = {
                key: value
                for key, value in {
                    "provider_user_id": event.viewer.provider_user_id,
                    "username": event.viewer.username,
                }.items()
                if value is not None
            } or None

        return LiveEventRecord(
            event_id=event.event_id,
            provider=event.provider.value,
            event_type=event.type.value,
            provider_event_id=event.provider_event_id,
            session_id=event.session_id,
            occurred_at=event.occurred_at,
            received_at=event.received_at,
            viewer_data=viewer_data,
            payload=event.payload,
            processing_status="RECEIVED",
        )

    def _mark_processed_sync(self, event_id: UUID) -> None:
        with self._session_factory.begin() as session:
            result = session.execute(
                update(LiveEventRecord)
                .where(LiveEventRecord.event_id == event_id)
                .values(
                    processing_status="PROCESSED",
                    error_code=None,
                    processed_at=datetime.now(UTC),
                )
            )
            if result.rowcount != 1:
                raise EventRepositoryError(f"Event record '{event_id}' was not found")

    def _release_sync(self, event: LiveEvent) -> None:
        with self._session_factory.begin() as session:
            session.execute(
                update(LiveEventRecord)
                .where(LiveEventRecord.event_id == event.event_id)
                .values(
                    processing_status="FAILED",
                    error_code="EVENT_PROCESSING_FAILED",
                    processed_at=None,
                )
            )
            if event.provider_event_id is not None:
                session.execute(
                    delete(EventDeduplicationKey).where(
                        EventDeduplicationKey.provider == event.provider.value,
                        EventDeduplicationKey.provider_event_id == event.provider_event_id,
                        EventDeduplicationKey.event_id == event.event_id,
                    )
                )

    def _get_record_sync(self, event_id: UUID) -> dict[str, Any] | None:
        with self._session_factory() as session:
            record = session.get(LiveEventRecord, event_id)
            if record is None:
                return None
            return {
                "event_id": record.event_id,
                "provider": record.provider,
                "event_type": record.event_type,
                "provider_event_id": record.provider_event_id,
                "session_id": record.session_id,
                "occurred_at": record.occurred_at,
                "received_at": record.received_at,
                "viewer_data": record.viewer_data,
                "payload": record.payload,
                "processing_status": record.processing_status,
                "error_code": record.error_code,
                "processed_at": record.processed_at,
            }

    def _count_records_sync(self) -> int:
        with self._session_factory() as session:
            return int(session.scalar(select(func.count()).select_from(LiveEventRecord)) or 0)

    def _purge_expired_sync(self, cutoff: datetime) -> int:
        with self._session_factory.begin() as session:
            result = session.execute(
                delete(LiveEventRecord).where(LiveEventRecord.received_at < cutoff)
            )
            return int(result.rowcount or 0)
