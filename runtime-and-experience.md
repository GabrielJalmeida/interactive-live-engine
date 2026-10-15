"""Runtime facade for Experience lifecycle, normalized dispatch, and output publication."""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping
from typing import Protocol

from pydantic import JsonValue

from backend.app.domain.events import LiveEvent, OutputEvent
from backend.app.runtime.event_router import EventRouter
from backend.app.runtime.experience_loader import ExperienceLoader, ExperienceMetadata
from backend.app.runtime.experience_manager import (
    ExperienceManager,
    InvalidExperienceOutputError,
    NoActiveExperienceError,
)


class OutputPublisher(Protocol):
    """Port implemented by the selected output transport."""

    async def publish(self, output: OutputEvent) -> int:
        """Publish one output and return the number of successful client deliveries."""
        ...


class EngineRuntime:
    """Coordinate registered Experiences and publish their outputs via an injected port."""

    def __init__(
        self,
        loader: ExperienceLoader | None = None,
        *,
        output_publisher: OutputPublisher | None = None,
    ) -> None:
        self.loader = loader or ExperienceLoader()
        self.manager = ExperienceManager(self.loader)
        self.router = EventRouter(self.manager)
        self._output_publisher = output_publisher

    @property
    def output_publisher(self) -> OutputPublisher | None:
        """Return the configured output transport, if composition supplied one."""

        return self._output_publisher

    def bind_output_publisher(self, publisher: OutputPublisher) -> None:
        """Bind a transport at the application composition root exactly once."""

        if self._output_publisher is not None and self._output_publisher is not publisher:
            raise RuntimeError("An output publisher is already bound to this EngineRuntime")
        self._output_publisher = publisher

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
        """Dispatch one normalized event and return the Experience's validated outputs."""

        return await self.router.route(event)

    async def publish(self, outputs: Iterable[OutputEvent]) -> int:
        """Publish outputs explicitly after the caller considers processing successful.

        This method deliberately remains separate from ``dispatch`` so the ingestion
        pipeline can later order persistence/status transitions before transport delivery.
        """

        output_batch = list(outputs)
        if not output_batch:
            return 0
        if self._output_publisher is None:
            raise RuntimeError("No output publisher is configured for this EngineRuntime")

        active_slug = self.manager.active_slug
        if active_slug is None:
            raise NoActiveExperienceError("Cannot publish Experience outputs without an active Experience")

        for index, output in enumerate(output_batch):
            if not isinstance(output, OutputEvent):
                raise InvalidExperienceOutputError(
                    f"Output at index {index} is not an OutputEvent instance"
                )
            if output.experience != active_slug:
                raise InvalidExperienceOutputError(
                    f"Output at index {index} identifies Experience '{output.experience}', "
                    f"expected '{active_slug}'"
                )

        delivered = 0
        for output in output_batch:
            delivered += await self._output_publisher.publish(output)
        return delivered

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
