"""Central ingestion use case, with deduplication and publication supplied by ports."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from typing import Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from backend.app.domain.events import LiveEvent, OutputEvent
from backend.app.runtime.engine_runtime import EngineRuntime
from backend.app.runtime.experience_manager import NoActiveExperienceError


class EventDeduplicationPort(Protocol):
    """Port for atomically reserving provider event identifiers.

    ``reserve`` returns the original internal event UUID when the incoming external
    identity was already seen, or ``None`` when the key is new/not eligible for dedupe.
    ``mark_processed`` records successful Experience execution before output publication.
    ``release`` records dispatch failure and releases a key so a deliberate retry is possible.
    """

    async def reserve(self, event: LiveEvent) -> UUID | None:
        """Reserve an eligible provider key; return the original event ID on duplicate."""
        ...

    async def mark_processed(self, event: LiveEvent) -> None:
        """Persist that the Experience handled this event successfully."""
        ...

    async def release(self, event: LiveEvent) -> None:
        """Mark a failed dispatch and release its dedupe claim when it owns the key."""
        ...


class InMemoryEventDeduplicationStore:
    """Development/test-only deduplication registry; state is lost at process restart."""

    def __init__(self) -> None:
        self._seen: dict[tuple[str, str], UUID] = {}
        self._statuses: dict[UUID, str] = {}
        self._lock = asyncio.Lock()

    async def reserve(self, event: LiveEvent) -> UUID | None:
        provider_event_id = event.provider_event_id
        async with self._lock:
            if provider_event_id is None:
                self._statuses[event.event_id] = "RECEIVED"
                return None

        key = (event.provider.value, provider_event_id)
        async with self._lock:
            original_event_id = self._seen.get(key)
            if original_event_id is not None:
                return original_event_id
            self._seen[key] = event.event_id
            self._statuses[event.event_id] = "RECEIVED"
            return None

    async def mark_processed(self, event: LiveEvent) -> None:
        """Track processed state for deterministic unit/integration tests."""

        async with self._lock:
            self._statuses[event.event_id] = "PROCESSED"

    async def release(self, event: LiveEvent) -> None:
        provider_event_id = event.provider_event_id
        key = (event.provider.value, provider_event_id) if provider_event_id is not None else None
        async with self._lock:
            if key is not None and self._seen.get(key) == event.event_id:
                del self._seen[key]
            self._statuses[event.event_id] = "FAILED"


class EventProcessingError(RuntimeError):
    """Raised when an Experience cannot process a normalized event."""

    def __init__(self, event_id: UUID) -> None:
        self.event_id = event_id
        super().__init__(f"Failed to process event '{event_id}'")


class EventPublicationError(RuntimeError):
    """Raised when processing succeeded but the output transport itself failed."""

    def __init__(self, event_id: UUID) -> None:
        self.event_id = event_id
        super().__init__(f"Failed to publish outputs for event '{event_id}'")


class EventPersistenceError(RuntimeError):
    """Raised when a successful dispatch cannot be marked durably processed."""

    def __init__(self, event_id: UUID) -> None:
        self.event_id = event_id
        super().__init__(f"Failed to persist processing status for event '{event_id}'")


class EventIngestionResult(BaseModel):
    """Stable response for successful and duplicate ingestion attempts."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["processed", "duplicate"]
    event_id: UUID
    duplicate_of_event_id: UUID | None = None
    outputs: list[OutputEvent] = Field(default_factory=list)
    delivered_clients: int = Field(default=0, ge=0)


class EventIngestionService:
    """Validate-flow orchestration: reserve, dispatch, then publish successful outputs."""

    def __init__(
        self,
        runtime: EngineRuntime,
        deduplication_store: EventDeduplicationPort,
        *,
        logger: logging.Logger | None = None,
    ) -> None:
        self._runtime = runtime
        self._deduplication_store = deduplication_store
        self._logger = logger or logging.getLogger("interactive_live_engine.ingestion")

    async def ingest(self, event: LiveEvent) -> EventIngestionResult:
        """Process one normalized event and report duplicate attempts deterministically."""

        try:
            duplicate_of_event_id = await self._deduplication_store.reserve(event)
        except Exception as exc:
            self._logger.exception(
                "Failed to persist event receipt or reserve deduplication key",
                extra=self._event_log_context(event),
            )
            raise EventPersistenceError(event.event_id) from exc

        if duplicate_of_event_id is not None:
            return EventIngestionResult(
                status="duplicate",
                event_id=event.event_id,
                duplicate_of_event_id=duplicate_of_event_id,
            )

        try:
            outputs = await self._runtime.dispatch(event)
        except NoActiveExperienceError:
            await self._release_failed_reservation(event)
            raise
        except BaseException as exc:
            await self._release_failed_reservation(event)
            if not isinstance(exc, Exception):
                raise
            self._logger.exception(
                "Event dispatch failed",
                extra=self._event_log_context(event),
            )
            raise EventProcessingError(event.event_id) from exc

        # Persist processing success before publishing. If publication subsequently fails,
        # the reservation remains so a retried provider event cannot run gameplay twice.
        try:
            await self._deduplication_store.mark_processed(event)
        except Exception as exc:
            self._logger.exception(
                "Experience processed the event but persistence of its status failed",
                extra=self._event_log_context(event),
            )
            # Keep the reservation: releasing it could cause a duplicate gameplay side effect.
            raise EventPersistenceError(event.event_id) from exc

        try:
            delivered_clients = await self._runtime.publish(outputs)
        except BaseException as exc:
            if not isinstance(exc, Exception):
                raise
            self._logger.exception(
                "Output publication failed after event processing",
                extra=self._event_log_context(event),
            )
            raise EventPublicationError(event.event_id) from exc

        return EventIngestionResult(
            status="processed",
            event_id=event.event_id,
            outputs=outputs,
            delivered_clients=delivered_clients,
        )

    async def _release_failed_reservation(self, event: LiveEvent) -> None:
        try:
            await self._deduplication_store.release(event)
        except Exception:
            self._logger.exception(
                "Failed to release event deduplication reservation",
                extra=self._event_log_context(event),
            )

    @staticmethod
    def _event_log_context(event: LiveEvent) -> Mapping[str, object]:
        return {
            "event_id": str(event.event_id),
            "provider": event.provider.value,
            "provider_event_id": event.provider_event_id,
            "event_type": event.type.value,
        }
