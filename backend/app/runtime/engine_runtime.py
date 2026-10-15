"""Runtime facade for Experience lifecycle, state, and normalized event dispatch."""

from __future__ import annotations

import logging
from collections.abc import Mapping

from pydantic import JsonValue

from backend.app.domain.events import LiveEvent, OutputEvent
from backend.app.runtime.event_router import EventRouter
from backend.app.runtime.experience_loader import ExperienceLoader, ExperienceMetadata
from backend.app.runtime.experience_manager import ExperienceManager


class EngineRuntime:
    """Coordinate registered Experiences without importing any concrete game module."""

    def __init__(self, loader: ExperienceLoader | None = None) -> None:
        self.loader = loader or ExperienceLoader()
        self.manager = ExperienceManager(self.loader)
        self.router = EventRouter(self.manager)

    async def start_experience(
        self,
        slug: str,
        *,
        config: Mapping[str, JsonValue] | None = None,
        logger: logging.Logger | None = None,
    ) -> ExperienceMetadata:
        return await self.manager.start(slug, config=config, logger=logger)

    async def stop_experience(self) -> bool:
        return await self.manager.stop()

    async def dispatch(self, event: LiveEvent) -> list[OutputEvent]:
        return await self.router.route(event)

    def list_experiences(self) -> list[ExperienceMetadata]:
        return self.loader.list_experiences()

    def state(self) -> dict[str, str | None]:
        """Return operational Runtime metadata without exposing gameplay state."""

        manager_status = self.manager.status
        if manager_status == "running":
            runtime_status = "running"
        elif manager_status == "failed":
            runtime_status = "failed"
        else:
            runtime_status = "stopped"
        return {
            "runtime": runtime_status,
            "active_experience": self.manager.active_slug,
            "experience_status": manager_status,
        }

    async def health(self) -> dict[str, JsonValue]:
        return await self.manager.health()
