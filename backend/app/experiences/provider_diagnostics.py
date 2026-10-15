"""Opt-in development Experience used to verify event-to-WebSocket flow without gameplay."""

from __future__ import annotations

from pydantic import JsonValue

from backend.app.domain.events import LiveEvent, OutputEvent
from backend.app.runtime.engine_runtime import EngineRuntime
from backend.app.runtime.experience import ExperienceContext
from backend.app.runtime.experience_loader import (
    ExperienceRegistrationError,
    UnknownExperienceError,
)


class ProviderDiagnosticsExperience:
    """Produce privacy-conscious output summaries for manual provider integration tests."""

    slug = "provider-diagnostics"
    name = "Provider Diagnostics"
    version = "1.0.0"

    def __init__(self) -> None:
        self._total_events = 0
        self._events_by_type: dict[str, int] = {}
        self._last_event_type: str | None = None

    async def start(self, context: ExperienceContext) -> None:
        """Reset counters for this activation; no external resources are allocated."""

        self._total_events = 0
        self._events_by_type = {}
        self._last_event_type = None
        context.logger.info("Provider diagnostics Experience started")

    async def stop(self, context: ExperienceContext) -> None:
        """No resources need releasing."""

        context.logger.info(
            "Provider diagnostics Experience stopped",
            extra={"total_events": self._total_events},
        )

    async def handle_event(self, event: LiveEvent, context: ExperienceContext) -> list[OutputEvent]:
        """Count the event and publish a safe summary; never echo comments or user identity."""

        self._total_events += 1
        event_type = event.type.value
        self._events_by_type[event_type] = self._events_by_type.get(event_type, 0) + 1
        self._last_event_type = event_type

        data: dict[str, JsonValue] = {
            "provider": event.provider.value,
            "event_type": event_type,
            "payload_fields": sorted(event.payload),
            "has_viewer": event.viewer is not None,
            "event_number": self._total_events,
        }
        if event.type.value == "COMMENT":
            text = event.payload.get("text")
            data["text_length"] = len(text) if isinstance(text, str) else 0
        elif event.type.value == "GIFT":
            gift_name = event.payload.get("gift_name")
            quantity = event.payload.get("quantity")
            if isinstance(gift_name, str):
                data["gift_name"] = gift_name
            if type(quantity) is int:
                data["quantity"] = quantity
        elif event.type.value == "LIKE":
            count = event.payload.get("count")
            total = event.payload.get("total")
            if type(count) is int:
                data["count"] = count
            if type(total) is int:
                data["total"] = total
        elif event.type.value == "JOIN":
            member_count = event.payload.get("member_count")
            if type(member_count) is int:
                data["member_count"] = member_count
        elif event.type.value == "FOLLOW":
            follow_count = event.payload.get("follow_count")
            if type(follow_count) is int:
                data["follow_count"] = follow_count
        elif event.type.value == "SHARE":
            share_count = event.payload.get("share_count")
            users_joined = event.payload.get("users_joined")
            if type(share_count) is int:
                data["share_count"] = share_count
            if type(users_joined) is int:
                data["users_joined"] = users_joined

        context.logger.debug(
            "Provider diagnostics processed normalized event",
            extra={"provider": event.provider.value, "event_type": event_type},
        )
        return [
            OutputEvent(
                type="PROVIDER_EVENT_RECEIVED",
                experience=self.slug,
                occurred_at=context.clock(),
                data=data,
            )
        ]

    async def get_state(self, context: ExperienceContext) -> dict[str, JsonValue]:
        """Expose counts only; do not return comments, usernames or raw provider payloads."""

        return {
            "status": "running",
            "total_events": self._total_events,
            "events_by_type": dict(self._events_by_type),
            "last_event_type": self._last_event_type,
        }

    async def health(self, context: ExperienceContext) -> dict[str, JsonValue]:
        """Report minimal diagnostic readiness."""

        return {"status": "ok", "total_events": self._total_events}


def register_provider_diagnostics(runtime: EngineRuntime) -> None:
    """Register the known diagnostic factory once, rejecting slug collisions."""

    try:
        existing = runtime.loader.metadata_for(ProviderDiagnosticsExperience.slug)
    except UnknownExperienceError:
        runtime.loader.register(
            slug=ProviderDiagnosticsExperience.slug,
            name=ProviderDiagnosticsExperience.name,
            version=ProviderDiagnosticsExperience.version,
            factory=ProviderDiagnosticsExperience,
        )
        return

    expected = {
        "slug": ProviderDiagnosticsExperience.slug,
        "name": ProviderDiagnosticsExperience.name,
        "version": ProviderDiagnosticsExperience.version,
    }
    if existing.model_dump() != expected:
        raise ExperienceRegistrationError(
            "The provider-diagnostics slug is already registered with different metadata"
        )
