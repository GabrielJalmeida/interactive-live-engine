"""Manual maintenance command to enforce configured event-record retention."""

import asyncio
from datetime import UTC, datetime, timedelta

from backend.app.config import Settings
from backend.app.persistence.database import create_database_engine, create_session_factory
from backend.app.persistence.event_repository import SqlAlchemyEventStore


def main() -> None:
    settings = Settings()
    engine = create_database_engine(settings.database_url)
    store = SqlAlchemyEventStore(create_session_factory(engine))
    cutoff = datetime.now(UTC) - timedelta(days=settings.event_record_retention_days)
    try:
        deleted = asyncio.run(store.purge_expired_before(cutoff))
    finally:
        engine.dispose()
    print(f"Deleted {deleted} event record(s) older than {cutoff.isoformat()}.")


if __name__ == "__main__":
    main()
