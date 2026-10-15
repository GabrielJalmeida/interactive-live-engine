"""Explicit registry for known Experience factories; no dynamic imports are allowed."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, TypeAdapter

from backend.app.runtime.experience import InteractiveExperience

ExperienceSlugValue = Annotated[
    str,
    StringConstraints(
        min_length=1,
        max_length=80,
        pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
        strip_whitespace=True,
    ),
]
_slug_adapter = TypeAdapter(ExperienceSlugValue)


class ExperienceRegistrationError(ValueError):
    """Raised when an Experience cannot be registered safely."""


class UnknownExperienceError(LookupError):
    """Raised when a slug is not present in the explicit registry."""


class InvalidExperienceDefinitionError(ValueError):
    """Raised when a factory does not create the registered Experience contract."""


class ExperienceMetadata(BaseModel):
    """Public metadata for a registered Experience."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    slug: ExperienceSlugValue
    name: str = Field(min_length=1, max_length=120)
    version: str = Field(min_length=1, max_length=32)


ExperienceFactory = Callable[[], InteractiveExperience]


@dataclass(frozen=True, slots=True)
class _Registration:
    metadata: ExperienceMetadata
    factory: ExperienceFactory


class ExperienceLoader:
    """Stores explicitly registered factories and validates instances on creation."""

    def __init__(self) -> None:
        self._registrations: dict[str, _Registration] = {}

    def register(
        self,
        *,
        slug: str,
        name: str,
        version: str,
        factory: ExperienceFactory,
    ) -> ExperienceMetadata:
        """Register a factory under validated metadata, rejecting duplicate slugs."""

        normalized_slug = _slug_adapter.validate_python(slug)
        metadata = ExperienceMetadata(slug=normalized_slug, name=name, version=version)
        if normalized_slug in self._registrations:
            raise ExperienceRegistrationError(
                f"Experience slug '{normalized_slug}' is already registered"
            )
        if not callable(factory):
            raise ExperienceRegistrationError("Experience factory must be callable")

        self._registrations[normalized_slug] = _Registration(metadata=metadata, factory=factory)
        return metadata

    def list_experiences(self) -> list[ExperienceMetadata]:
        """Return registered metadata in deterministic slug order."""

        return [self._registrations[slug].metadata for slug in sorted(self._registrations)]

    def metadata_for(self, slug: str) -> ExperienceMetadata:
        """Return metadata for a registered slug or raise a clear error."""

        registration = self._registrations.get(slug)
        if registration is None:
            raise UnknownExperienceError(f"Experience '{slug}' is not registered")
        return registration.metadata

    def create(self, slug: str) -> InteractiveExperience:
        """Create a registered Experience and check its declaration and required methods."""

        registration = self._registrations.get(slug)
        if registration is None:
            raise UnknownExperienceError(f"Experience '{slug}' is not registered")

        instance = registration.factory()
        expected = registration.metadata
        actual = {
            "slug": getattr(instance, "slug", None),
            "name": getattr(instance, "name", None),
            "version": getattr(instance, "version", None),
        }
        expected_values = expected.model_dump()
        if actual != expected_values:
            raise InvalidExperienceDefinitionError(
                f"Factory for '{slug}' returned mismatched metadata: expected "
                f"{expected_values}, received {actual}"
            )

        required_methods = ("start", "stop", "handle_event", "get_state", "health")
        missing_methods = [
            method for method in required_methods if not callable(getattr(instance, method, None))
        ]
        if missing_methods:
            raise InvalidExperienceDefinitionError(
                f"Experience '{slug}' is missing callable methods: {', '.join(missing_methods)}"
            )
        return instance
