"""Thin routing boundary between normalized events and the active Experience."""

from backend.app.domain.events import LiveEvent, OutputEvent
from backend.app.runtime.experience_manager import ExperienceManager


class EventRouter:
    """Route events without interpreting provider-specific or gameplay semantics."""

    def __init__(self, manager: ExperienceManager) -> None:
        self._manager = manager

    async def route(self, event: LiveEvent) -> list[OutputEvent]:
        return await self._manager.dispatch(event)
