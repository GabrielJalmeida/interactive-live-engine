"""Public contract and context supplied to gameplay Experiences."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from pydantic import JsonValue

from backend.app.domain.events import LiveEvent, OutputEvent, utc_now


@dataclass(frozen=True, slots=True)
class ExperienceContext:
    """Dependencies and configuration scoped to one Experience activation."""

    experience_slug: str
    config: Mapping[str, JsonValue] = field(default_factory=dict)
    logger: logging.Logger = field(
        default_factory=lambda: logging.getLogger("interactive_live_engine.experience")
    )
    clock: Callable[[], datetime] = utc_now


class InteractiveExperience(Protocol):
    """Required lifecycle and event interface implemented by a game Experience."""

    slug: str
    name: str
    version: str

    async def start(self, context: ExperienceContext) -> None:
        """Initialize the Experience's in-memory resources and state."""
        ...

    async def stop(self, context: ExperienceContext) -> None:
        """Release resources held by this activation."""
        ...

    async def handle_event(self, event: LiveEvent, context: ExperienceContext) -> list[OutputEvent]:
        """Apply one normalized event and return zero or more output envelopes."""
        ...

    async def get_state(self, context: ExperienceContext) -> dict[str, JsonValue]:
        """Return a JSON-compatible diagnostic state, not a required full snapshot."""
        ...

    async def health(self, context: ExperienceContext) -> dict[str, JsonValue]:
        """Return a JSON-compatible health report for this activation."""
        ...
