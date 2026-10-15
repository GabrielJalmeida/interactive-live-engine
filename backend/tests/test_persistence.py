"""Persistence and migration integration tests using isolated temporary SQLite databases."""

import asyncio
from datetime import UTC, datetime
from pathlib import Path

from alembic import command
from alembic.config import Config
from backend.app.domain.events import EventProvider, EventType, LiveEvent, OutputEvent
from sqlalchemy import inspect
from sqlalchemy.orm import sessionmaker

from backend.app.application.event_ingestion import EventIngestionService, EventPublicationError
from backend.app.persistence.database import create_database_engine, create_session_factory
from backend.app.persistence.event_repository import SqlAlchemyEventStore
from backend.app.persistence.models import Base, EventDeduplicationKey

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def make_event(
    provider_event_id: str | None = "external-001",
    *,
    event_id=None,
    provider: EventProvider = EventProvider.SIMULATOR,
) -> LiveEvent:
    values = {
        "type": EventType.COMMENT,
        "provider": provider,
        "provider_event_id": provider_event_id,
        "occurred_at": datetime(2026, 10, 15, 20, 0, tzinfo=UTC),
        "payload": {"text": "hello"},
    }
    if event_id is not None:
        values["event_id"] = event_id
    return LiveEvent.model_validate(values)


def make_store(database_path: Path) -> tuple[SqlAlchemyEventStore, object, sessionmaker]:
    engine = create_database_engine(f"sqlite:///{database_path.as_posix()}")
    Base.metadata.create_all(engine)
    session_factory = create_session_factory(engine)
    return SqlAlchemyEventStore(session_factory), engine, session_factory


def test_reserve_persists_receipt_and_duplicate_returns_original_event_id(tmp_path: Path) -> None:
    async def scenario() -> None:
        store, engine, _sessions = make_store(tmp_path / "events.db")
        first = make_event("same-provider-id")
        retry = make_event("same-provider-id")

        try:
            assert await store.reserve(first) is None
            assert await store.reserve(retry) == first.event_id
            assert await store.count_records() == 1

            record = await store.get_record(first.event_id)
            assert record is not None
            assert record["processing_status"] == "RECEIVED"
            assert record["provider_event_id"] == "same-provider-id"
            assert record["payload"] == {"text": "hello"}
        finally:
            engine.dispose()

    asyncio.run(scenario())


def test_mark_processed_persists_status_and_utc_timestamp(tmp_path: Path) -> None:
    async def scenario() -> None:
        store, engine, _ = make_store(tmp_path / "processed.db")
        event = make_event()
        try:
            assert await store.reserve(event) is None
            await store.mark_processed(event)
            record = await store.get_record(event.event_id)
            assert record is not None
            assert record["processing_status"] == "PROCESSED"
            assert record["error_code"] is None
            assert record["processed_at"].tzinfo is UTC
        finally:
            engine.dispose()

    asyncio.run(scenario())


def test_failed_dispatch_keeps_history_but_releases_key_for_retry(tmp_path: Path) -> None:
    async def scenario() -> None:
        store, engine, sessions = make_store(tmp_path / "retry.db")
        first = make_event("retry-me")
        retry = make_event("retry-me")
        try:
            assert await store.reserve(first) is None
            await store.release(first)

            failed = await store.get_record(first.event_id)
            assert failed is not None
            assert failed["processing_status"] == "FAILED"
            assert failed["error_code"] == "EVENT_PROCESSING_FAILED"

            assert await store.reserve(retry) is None
            assert await store.count_records() == 2
            assert await store.get_record(retry.event_id) is not None
            with sessions() as session:
                claim = session.get(
                    EventDeduplicationKey,
                    (retry.provider.value, "retry-me"),
                )
                assert claim is not None and claim.event_id == retry.event_id
        finally:
            engine.dispose()

    asyncio.run(scenario())


def test_events_without_external_id_are_recorded_but_not_collapsed(tmp_path: Path) -> None:
    async def scenario() -> None:
        store, engine, _ = make_store(tmp_path / "no-external-id.db")
        first = make_event(None)
        second = make_event(None)
        try:
            assert await store.reserve(first) is None
            assert await store.reserve(second) is None
            assert await store.count_records() == 2
        finally:
            engine.dispose()

    asyncio.run(scenario())


def test_concurrent_same_external_id_has_exactly_one_reservation_winner(tmp_path: Path) -> None:
    async def scenario() -> None:
        store, engine, _ = make_store(tmp_path / "concurrent.db")
        events = [make_event("concurrent-id") for _ in range(8)]
        try:
            results = await asyncio.gather(*(store.reserve(event) for event in events))
            winners = [events[index] for index, result in enumerate(results) if result is None]
            duplicates = [result for result in results if result is not None]

            assert len(winners) == 1
            assert len(duplicates) == len(events) - 1
            assert all(original_id == winners[0].event_id for original_id in duplicates)
            assert await store.count_records() == 1
        finally:
            engine.dispose()

    asyncio.run(scenario())


def test_migration_creates_schema_from_an_empty_database(tmp_path: Path, monkeypatch) -> None:
    database_path = tmp_path / "migration.db"
    database_url = f"sqlite:///{database_path.as_posix()}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    config = Config(str(PROJECT_ROOT / "alembic.ini"))

    command.upgrade(config, "head")
    command.check(config)
    engine = create_database_engine(database_url)
    try:
        inspector = inspect(engine)
        table_names = set(inspector.get_table_names())
        assert {"alembic_version", "live_event_records", "event_deduplication_keys"} <= table_names

        # Composite primary key is the durable provider identity uniqueness constraint.
        pk = inspector.get_pk_constraint("event_deduplication_keys")
        assert pk["constrained_columns"] == ["provider", "provider_event_id"]
        assert any(
            index["name"] == "ix_live_event_records_processing_status"
            for index in inspector.get_indexes("live_event_records")
        )
    finally:
        engine.dispose()
    monkeypatch.delenv("DATABASE_URL", raising=False)


class FakeRuntime:
    """Minimal runtime to exercise ingestion status persistence without gameplay."""

    def __init__(self, *, fail_publish: bool = False) -> None:
        self.dispatch_count = 0
        self.fail_publish = fail_publish

    async def dispatch(self, event: LiveEvent) -> list[OutputEvent]:
        self.dispatch_count += 1
        return [OutputEvent(type="TEST_OUTPUT", experience="test-game", data={"ok": True})]

    async def publish(self, outputs: list[OutputEvent]) -> int:
        if self.fail_publish:
            raise RuntimeError("simulated transport failure")
        return 0


def test_ingestion_persists_processed_before_output_publish(tmp_path: Path) -> None:
    async def scenario() -> None:
        store, engine, _ = make_store(tmp_path / "ingestion.db")
        runtime = FakeRuntime()
        service = EventIngestionService(runtime, store)  # type: ignore[arg-type]
        event = make_event("processed-before-publish")
        try:
            result = await service.ingest(event)
            assert result.status == "processed"
            record = await store.get_record(event.event_id)
            assert record is not None
            assert record["processing_status"] == "PROCESSED"
            assert record["processed_at"] is not None
        finally:
            engine.dispose()

    asyncio.run(scenario())


def test_publish_failure_keeps_processed_record_and_prevents_redispatch(tmp_path: Path) -> None:
    async def scenario() -> None:
        store, engine, _ = make_store(tmp_path / "publish-failure.db")
        runtime = FakeRuntime(fail_publish=True)
        service = EventIngestionService(runtime, store)  # type: ignore[arg-type]
        first = make_event("processed-but-not-delivered")
        retry = make_event("processed-but-not-delivered")
        try:
            try:
                await service.ingest(first)
            except EventPublicationError:
                pass
            else:
                raise AssertionError("publication failure should be represented explicitly")

            stored = await store.get_record(first.event_id)
            assert stored is not None
            assert stored["processing_status"] == "PROCESSED"

            duplicate = await service.ingest(retry)
            assert duplicate.status == "duplicate"
            assert duplicate.duplicate_of_event_id == first.event_id
            assert runtime.dispatch_count == 1
        finally:
            engine.dispose()

    asyncio.run(scenario())


def test_retention_purge_removes_old_history_and_its_dedupe_claim(tmp_path: Path) -> None:
    async def scenario() -> None:
        store, engine, sessions = make_store(tmp_path / "retention.db")
        event = make_event("expire-me")
        try:
            assert await store.reserve(event) is None
            deleted = await store.purge_expired_before(datetime(2026, 10, 16, tzinfo=UTC))
            assert deleted == 1
            assert await store.get_record(event.event_id) is None
            assert await store.count_records() == 0
            with sessions() as session:
                assert (
                    session.get(EventDeduplicationKey, (event.provider.value, "expire-me")) is None
                )
        finally:
            engine.dispose()

    asyncio.run(scenario())


def test_persistence_minimizes_viewer_data(tmp_path: Path) -> None:
    async def scenario() -> None:
        store, engine, _ = make_store(tmp_path / "viewer.db")
        event = LiveEvent(
            type=EventType.COMMENT,
            provider=EventProvider.SIMULATOR,
            provider_event_id="viewer-minimum",
            occurred_at=datetime(2026, 10, 15, 20, 0, tzinfo=UTC),
            viewer={
                "provider_user_id": "stable-id",
                "username": "maria",
                "display_name": "Maria Full Name",
                "avatar_url": "https://example.com/avatar.png",
            },
            payload={"text": "hello"},
        )
        try:
            assert await store.reserve(event) is None
            record = await store.get_record(event.event_id)
            assert record is not None
            assert record["viewer_data"] == {
                "provider_user_id": "stable-id",
                "username": "maria",
            }
        finally:
            engine.dispose()

    asyncio.run(scenario())
