"""Persistence adapters for infrastructure-owned data."""

from backend.app.persistence.event_repository import SqlAlchemyEventStore

__all__ = ["SqlAlchemyEventStore"]
