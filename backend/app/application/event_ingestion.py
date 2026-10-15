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
    ``release`` removes a reservation after dispatch failed, allowing a deliberate retry.
    A persistent implementation will replace the in-memory adapter in the persistence slice.
    """

    async def reserve(self, event: LiveEvent) -> UUID | None:
        """Reserve an eligible provider key; return the original event ID on duplicate."""
        ...

    async def release(self, event: LiveEvent) -> None:
        """Release this event's reservation if it owns the key."""
        ...


class InMemoryEventDeduplicationStore:
    """Development/test-only deduplication registry; state is lost at process restart."""

    def __init__(self) -> None:
        self._seen: dict[tuple[str, str], UUID] = {}
        self._lock = asyncio.Lock()

    async def reserve(self, event: LiveEvent) -> UUID | None:
        provider_event_id = event.provider_event_id
        if provider_event_id is None:
            return None

        key = (event.provider.value, provider_event_id)
        async with self._lock:
            original_event_id = self._seen.get(key)
            if original_event_id is not None:
                return original_event_id
            self._seen[key] = event.event_id
            return None

    async def release(self, event: LiveEvent) -> None:
        provider_event_id = event.provider_event_id
        if provider_event_id is None:
            return

        key = (event.provider.value, provider_event_id)
        async with self._lock:
            if self._seen.get(key) == event.event_id:
                del self._seen[key]


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

        duplicate_of_event_id = await self._deduplication_store.reserve(event)
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

        # Keep the reservation once the Experience has processed the event. If delivery
        # later fails, blindly retrying could execute gameplay side effects twice; durable
        # output delivery is intentionally deferred to the outbox/reliability slice.
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
