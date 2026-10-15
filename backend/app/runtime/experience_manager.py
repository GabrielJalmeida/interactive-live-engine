"""Lifecycle and event dispatch for the single active Experience in the MVP."""

from __future__ import annotations

import copy
import logging
from collections.abc import Mapping

from pydantic import JsonValue, TypeAdapter

from backend.app.domain.events import LiveEvent, OutputEvent
from backend.app.runtime.experience import ExperienceContext, InteractiveExperience
from backend.app.runtime.experience_loader import (
    ExperienceLoader,
    ExperienceMetadata,
)

_JSON_STATE_ADAPTER = TypeAdapter(dict[str, JsonValue])


class ExperienceLifecycleError(RuntimeError):
    """Raised when a requested Experience lifecycle transition is invalid."""


class NoActiveExperienceError(RuntimeError):
    """Raised when an event or state query requires an active Experience."""


class InvalidExperienceOutputError(ValueError):
    """Raised when an Experience returns output that violates the Engine contract."""


class ExperienceManager:
    """Owns one Experience instance and its context for a single activation."""

    def __init__(self, loader: ExperienceLoader) -> None:
        self._loader = loader
        self._active: InteractiveExperience | None = None
        self._context: ExperienceContext | None = None
        self._active_metadata: ExperienceMetadata | None = None
        self._status = "stopped"

    @property
    def status(self) -> str:
        return self._status

    @property
    def active_slug(self) -> str | None:
        return self._active_metadata.slug if self._active_metadata else None

    async def start(
        self,
        slug: str,
        *,
        config: Mapping[str, JsonValue] | None = None,
        logger: logging.Logger | None = None,
    ) -> ExperienceMetadata:
        """Instantiate and start one registered Experience, cleaning up on failure."""

        if self._status in {"starting", "running", "stopping"}:
            raise ExperienceLifecycleError(
                f"Cannot start '{slug}' while Runtime status is '{self._status}'"
            )

        metadata = self._loader.metadata_for(slug)
        self._status = "starting"
        instance = None
        context = ExperienceContext(
            experience_slug=slug,
            config=copy.deepcopy(dict(config or {})),
            logger=logger or logging.getLogger(f"interactive_live_engine.experience.{slug}"),
        )
        try:
            instance = self._loader.create(slug)
            await instance.start(context)
        except BaseException:
            # start() may allocate resources before failing; attempt best-effort cleanup,
            # preserve the initialization error, and never leave the Runtime marked running.
            if instance is not None:
                try:
                    await instance.stop(context)
                except BaseException:
                    context.logger.exception(
                        "Experience cleanup after failed start also failed",
                        extra={"experience_slug": slug},
                    )
            self._active = None
            self._context = None
            self._active_metadata = None
            self._status = "failed"
            raise

        self._active = instance
        self._context = context
        self._active_metadata = metadata
        self._status = "running"
        return metadata

    async def stop(self) -> bool:
        """Stop the active Experience. Stopping while inactive is an idempotent no-op."""

        if self._active is None or self._context is None:
            return False

        instance = self._active
        context = self._context
        self._status = "stopping"
        try:
            await instance.stop(context)
        except BaseException:
            self._status = "failed"
            raise
        else:
            self._status = "stopped"
            return True
        finally:
            self._active = None
            self._context = None
            self._active_metadata = None

    async def dispatch(self, event: LiveEvent) -> list[OutputEvent]:
        """Send a normalized event to the active Experience and validate its outputs."""

        instance, context = self._require_active()
        outputs = await instance.handle_event(event, context)
        if not isinstance(outputs, list):
            raise InvalidExperienceOutputError(
                "Experience.handle_event() must return a list of OutputEvent instances"
            )

        for index, output in enumerate(outputs):
            if not isinstance(output, OutputEvent):
                raise InvalidExperienceOutputError(
                    f"Output at index {index} is not an OutputEvent instance"
                )
            if output.experience != context.experience_slug:
                raise InvalidExperienceOutputError(
                    f"Output at index {index} identifies Experience '{output.experience}', "
                    f"expected '{context.experience_slug}'"
                )
        return outputs

    async def get_state(self) -> dict[str, JsonValue]:
        """Return the active Experience state after validating JSON compatibility."""

        instance, context = self._require_active()
        state = await instance.get_state(context)
        if not isinstance(state, dict):
            raise TypeError("Experience.get_state() must return a dictionary")
        return _JSON_STATE_ADAPTER.validate_python(state)

    async def health(self) -> dict[str, JsonValue]:
        """Return a concise state if no Experience is active, otherwise its health report."""

        if self._active is None or self._context is None:
            return {"status": self._status}
        report = await self._active.health(self._context)
        if not isinstance(report, dict):
            raise TypeError("Experience.health() must return a dictionary")
        return _JSON_STATE_ADAPTER.validate_python(report)

    def _require_active(self) -> tuple[InteractiveExperience, ExperienceContext]:
        if self._active is None or self._context is None:
            raise NoActiveExperienceError("No Experience is active")
        return self._active, self._context
