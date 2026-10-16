"""Local-only tests for TikTokLive normalization and listener lifecycle; no live connection."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from backend.app.config import Settings
from backend.app.domain.events import EventType, LiveEvent, Viewer
from backend.app.main import create_app
from backend.app.providers.tiktok_live import (
    TikTokLiveAdapter,
    TikTokLiveBindings,
    TikTokLiveConfigurationError,
    TikTokLiveEventNormalizer,
)


class FakeIngestionService:
    def __init__(self, *, fail: Exception | None = None, result_status: str = "processed") -> None:
        self.events: list[LiveEvent] = []
        self.fail = fail
        self.result_status = result_status

    async def ingest(self, event: LiveEvent) -> SimpleNamespace:
        if self.fail is not None:
            raise self.fail
        self.events.append(event)
        return SimpleNamespace(status=self.result_status)


class FakeTikTokClient:
    def __init__(self, *, unique_id: str) -> None:
        self.unique_id = unique_id
        self.listeners: dict[type[object], Callable[[object], Awaitable[None]]] = {}
        self.started = False
        self.disconnected = False
        self._finish = asyncio.Event()
        self.connection_task: asyncio.Task[None] | None = None
        self.fetch_live_check: bool | None = None
        self.close_client: bool | None = None

    def add_listener(
        self, event_type: type[object], listener: Callable[[object], Awaitable[None]]
    ) -> None:
        self.listeners[event_type] = listener

    async def start(self, *, fetch_live_check: bool = True) -> asyncio.Task[None]:
        self.started = True
        self.fetch_live_check = fetch_live_check
        self.connection_task = asyncio.create_task(self._finish.wait())
        return self.connection_task

    async def disconnect(self, close_client: bool = False) -> None:
        self.disconnected = True
        self.close_client = close_client
        self._finish.set()

    async def emit(self, event_cls: type[object], event: object) -> None:
        await self.listeners[event_cls](event)


class FakeEventTypes:
    """Distinct fake classes in the same shape as the public SDK event classes."""

    ConnectEvent = type("ConnectEvent", (), {})
    DisconnectEvent = type("DisconnectEvent", (), {})
    CommentEvent = type("CommentEvent", (), {})
    GiftEvent = type("GiftEvent", (), {})
    LikeEvent = type("LikeEvent", (), {})
    FollowEvent = type("FollowEvent", (), {})
    ShareEvent = type("ShareEvent", (), {})
    JoinEvent = type("JoinEvent", (), {})


EVENT_BINDINGS = {
    EventType.CONNECT: FakeEventTypes.ConnectEvent,
    EventType.DISCONNECT: FakeEventTypes.DisconnectEvent,
    EventType.COMMENT: FakeEventTypes.CommentEvent,
    EventType.GIFT: FakeEventTypes.GiftEvent,
    EventType.LIKE: FakeEventTypes.LikeEvent,
    EventType.FOLLOW: FakeEventTypes.FollowEvent,
    EventType.SHARE: FakeEventTypes.ShareEvent,
    EventType.JOIN: FakeEventTypes.JoinEvent,
}


def make_bindings(clients: list[FakeTikTokClient]) -> TikTokLiveBindings:
    def factory(*, unique_id: str) -> FakeTikTokClient:
        client = FakeTikTokClient(unique_id=unique_id)
        clients.append(client)
        return client

    return TikTokLiveBindings(client_factory=factory, event_types=EVENT_BINDINGS)


def test_comment_event_is_normalized_without_leaking_sdk_objects() -> None:
    normalizer = TikTokLiveEventNormalizer()
    provider_event = SimpleNamespace(
        comment="hello engine",
        common=SimpleNamespace(msg_id="message-123"),
        user=SimpleNamespace(id=42, unique_id="viewer_42", nickname="Viewer 42"),
    )

    normalized = normalizer.normalize(EventType.COMMENT, provider_event, session_id="room-9")

    assert normalized is not None
    assert normalized.type is EventType.COMMENT
    assert normalized.provider.value == "tiktok"
    assert normalized.provider_event_id == "message-123"
    assert normalized.session_id == "room-9"
    assert normalized.payload == {"text": "hello engine"}
    assert normalized.viewer == Viewer(
        provider_user_id="42", username="viewer_42", display_name="Viewer 42"
    )
    assert normalized.occurred_at.tzinfo is not None
    assert normalized.received_at.tzinfo is not None


def test_normalizer_accepts_v3_comment_content_when_compatibility_alias_is_absent() -> None:
    normalized = TikTokLiveEventNormalizer().normalize(
        EventType.COMMENT, SimpleNamespace(content="v3 text", user=None)
    )

    assert normalized is not None
    assert normalized.payload == {"text": "v3 text"}


def test_gift_streak_intermediate_updates_are_ignored_and_final_count_is_preserved() -> None:
    normalizer = TikTokLiveEventNormalizer()
    intermediate = SimpleNamespace(streaking=True)
    final = SimpleNamespace(
        streaking=False,
        repeat_count=7,
        log_id="gift-log-1",
        gift=SimpleNamespace(id=5655, name="Rose"),
        user=SimpleNamespace(unique_id="gifter", nickname="Gifter", id=55),
    )

    assert normalizer.normalize(EventType.GIFT, intermediate) is None
    normalized = normalizer.normalize(EventType.GIFT, final, session_id="room-1")

    assert normalized is not None
    assert normalized.provider_event_id == "gift-log-1"
    assert normalized.session_id == "room-1"
    assert normalized.payload == {
        "quantity": 7,
        "streaking": False,
        "gift_name": "Rose",
        "gift_id": 5655,
    }


@pytest.mark.parametrize(
    ("kind", "provider_event", "expected_payload"),
    [
        (EventType.CONNECT, SimpleNamespace(room_id=12345), {"room_id": 12345}),
        (EventType.DISCONNECT, SimpleNamespace(), {}),
        (EventType.LIKE, SimpleNamespace(count=4, total=98), {"count": 4, "total": 98}),
        (EventType.FOLLOW, SimpleNamespace(follow_count=3), {"follow_count": 3}),
        (
            EventType.SHARE,
            SimpleNamespace(share_count=2, users_joined=5),
            {"share_count": 2, "users_joined": 5},
        ),
        (EventType.JOIN, SimpleNamespace(member_count=42), {"member_count": 42}),
    ],
)
def test_normalizer_maps_supported_non_text_event_types(
    kind: EventType, provider_event: object, expected_payload: dict[str, Any]
) -> None:
    normalized = TikTokLiveEventNormalizer().normalize(kind, provider_event)

    assert normalized is not None
    assert normalized.type is kind
    assert normalized.payload == expected_payload
    if kind is EventType.CONNECT:
        assert normalized.session_id == "12345"


@pytest.mark.asyncio
async def test_adapter_registers_handlers_normalizes_events_and_stops_client() -> None:
    clients: list[FakeTikTokClient] = []
    ingestion = FakeIngestionService()
    adapter = TikTokLiveAdapter(
        ingestion,
        enabled=True,
        username="@engine_tester",
        bindings=make_bindings(clients),
    )

    await adapter.start()
    assert len(clients) == 1
    client = clients[0]
    assert client.unique_id == "engine_tester"
    assert client.started is True
    assert client.fetch_live_check is True
    assert set(client.listeners) == set(EVENT_BINDINGS.values())
    assert adapter.snapshot()["status"] == "starting"

    await client.emit(FakeEventTypes.ConnectEvent, SimpleNamespace(room_id=901))
    await client.emit(
        FakeEventTypes.CommentEvent,
        SimpleNamespace(comment="test comment", user=SimpleNamespace(nickname="Tester")),
    )
    await client.emit(
        FakeEventTypes.GiftEvent,
        SimpleNamespace(streaking=True),
    )
    await client.emit(FakeEventTypes.LikeEvent, SimpleNamespace(count=3, total=3))

    state = adapter.snapshot()
    assert state["status"] == "connected"
    assert state["provider_events_received"] == 4
    assert state["normalized_events"] == 3
    assert state["processed_events"] == 3
    assert state["ignored_gift_updates"] == 1
    assert [event.type for event in ingestion.events] == [
        EventType.CONNECT,
        EventType.COMMENT,
        EventType.LIKE,
    ]
    assert ingestion.events[1].session_id == "901"

    await adapter.stop()
    assert client.disconnected is True
    assert client.close_client is True
    assert adapter.snapshot()["status"] == "stopped"


@pytest.mark.asyncio
async def test_connection_task_completion_updates_status_even_without_connect_event() -> None:
    clients: list[FakeTikTokClient] = []
    adapter = TikTokLiveAdapter(
        FakeIngestionService(),
        enabled=True,
        username="streamer",
        bindings=make_bindings(clients),
    )

    await adapter.start()
    assert adapter.snapshot()["status"] == "starting"
    clients[0]._finish.set()
    assert adapter._monitor_task is not None
    await adapter._monitor_task

    assert adapter.snapshot()["status"] == "disconnected"
    await adapter.stop()


@pytest.mark.asyncio
async def test_connection_failure_marks_provider_failed_without_exposing_exception(
    caplog,
) -> None:
    clients: list[FakeTikTokClient] = []

    class FailingConnectionClient(FakeTikTokClient):
        async def start(self, *, fetch_live_check: bool = True) -> asyncio.Task[None]:
            self.started = True
            self.fetch_live_check = fetch_live_check

            async def fail() -> None:
                raise RuntimeError("private connection details")

            self.connection_task = asyncio.create_task(fail())
            return self.connection_task

    def factory(*, unique_id: str) -> FakeTikTokClient:
        client = FailingConnectionClient(unique_id=unique_id)
        clients.append(client)
        return client

    adapter = TikTokLiveAdapter(
        FakeIngestionService(),
        enabled=True,
        username="streamer",
        bindings=TikTokLiveBindings(
            client_factory=factory,
            event_types=EVENT_BINDINGS,
        ),
    )

    await adapter.start()
    monitor_task = adapter._monitor_task
    assert monitor_task is not None

    await monitor_task

    state = adapter.snapshot()
    assert state["status"] == "failed"
    assert state["last_error_code"] == "provider_connection_runtimeerror"
    assert "private connection details" not in caplog.text

    await adapter.stop()

    assert clients[0].disconnected is True
    assert adapter.snapshot()["status"] == "stopped"


@pytest.mark.asyncio
async def test_unexpected_connection_cancellation_marks_provider_failed() -> None:
    clients: list[FakeTikTokClient] = []
    adapter = TikTokLiveAdapter(
        FakeIngestionService(),
        enabled=True,
        username="streamer",
        bindings=make_bindings(clients),
    )

    await adapter.start()

    connection_task = clients[0].connection_task
    monitor_task = adapter._monitor_task

    assert connection_task is not None
    assert monitor_task is not None

    connection_task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await monitor_task

    state = adapter.snapshot()
    assert state["status"] == "failed"
    assert state["last_error_code"] == "provider_connection_cancelled"

    await adapter.stop()
    assert adapter.snapshot()["status"] == "stopped"


@pytest.mark.asyncio
async def test_disconnected_provider_must_be_stopped_before_restarting() -> None:
    clients: list[FakeTikTokClient] = []
    adapter = TikTokLiveAdapter(
        FakeIngestionService(),
        enabled=True,
        username="streamer",
        bindings=make_bindings(clients),
    )

    await adapter.start()
    await clients[0].emit(FakeEventTypes.DisconnectEvent, SimpleNamespace())

    with pytest.raises(TikTokLiveConfigurationError, match=r"Call stop\(\) before restarting"):
        await adapter.start()

    assert len(clients) == 1
    await adapter.stop()


@pytest.mark.asyncio
async def test_adapter_tracks_duplicates_and_catches_ingestion_failures(caplog) -> None:
    duplicate_adapter_clients: list[FakeTikTokClient] = []
    duplicate_adapter = TikTokLiveAdapter(
        FakeIngestionService(result_status="duplicate"),
        enabled=True,
        username="streamer",
        bindings=make_bindings(duplicate_adapter_clients),
    )
    await duplicate_adapter.start()
    await duplicate_adapter_clients[0].emit(
        FakeEventTypes.CommentEvent, SimpleNamespace(comment="again", user=None)
    )
    assert duplicate_adapter.snapshot()["duplicate_events"] == 1
    await duplicate_adapter.stop()

    failing_clients: list[FakeTikTokClient] = []
    failing_adapter = TikTokLiveAdapter(
        FakeIngestionService(fail=RuntimeError("private payload details")),
        enabled=True,
        username="streamer",
        bindings=make_bindings(failing_clients),
    )
    await failing_adapter.start()
    await failing_clients[0].emit(
        FakeEventTypes.CommentEvent, SimpleNamespace(comment="private text", user=None)
    )
    snapshot = failing_adapter.snapshot()
    assert snapshot["failed_events"] == 1
    assert snapshot["last_error_code"] == "event_ingestion_runtimeerror"
    assert "private" not in str(snapshot)
    assert "private payload details" not in caplog.text
    assert "private text" not in caplog.text
    await failing_adapter.stop()


@pytest.mark.asyncio
async def test_disabled_adapter_does_not_import_sdk_or_create_client() -> None:
    adapter = TikTokLiveAdapter(FakeIngestionService(), enabled=False, username=None)

    await adapter.start()

    assert adapter.snapshot()["status"] == "disabled"
    assert adapter.snapshot()["enabled"] is False
    assert adapter.snapshot()["provider_events_received"] == 0


def test_tiktok_settings_require_a_username_only_when_enabled() -> None:
    settings = Settings(_env_file=None, app_env="test")
    assert settings.tiktok_live_enabled is False
    assert settings.tiktok_live_username is None

    with pytest.raises(ValueError, match="TIKTOK_LIVE_USERNAME is required"):
        Settings(_env_file=None, tiktok_live_enabled=True)

    configured = Settings(
        _env_file=None,
        tiktok_live_enabled=True,
        tiktok_live_username=" @MyChannel ",
    )
    assert configured.tiktok_live_username == "MyChannel"


def test_provider_status_endpoint_is_safe_when_provider_is_disabled() -> None:
    client = TestClient(create_app(Settings(_env_file=None, app_env="test")))

    response = client.get("/api/v1/providers/tiktok")

    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "tiktok"
    assert body["enabled"] is False
    assert body["status"] == "disabled"
    assert body["provider_events_received"] == 0
    assert "username" not in body
    assert "payload" not in body


def test_diagnostic_experience_endpoint_routes_simulated_events_to_safe_output() -> None:
    client = TestClient(create_app(Settings(_env_file=None, app_env="test")))

    with client:
        started = client.post("/api/v1/dev/provider-diagnostics/start")
        assert started.status_code == 200
        assert started.json() == {
            "status": "running",
            "experience": "provider-diagnostics",
        }

        response = client.post(
            "/api/v1/dev/events",
            json={"type": "COMMENT", "payload": {"text": "private comment text"}},
        )
        assert response.status_code == 200
        output = response.json()["outputs"][0]
        assert output["type"] == "PROVIDER_EVENT_RECEIVED"
        assert output["experience"] == "provider-diagnostics"
        assert output["data"]["event_type"] == "COMMENT"
        assert output["data"]["text_length"] == len("private comment text")
        assert "private comment text" not in str(output)

        stopped = client.post("/api/v1/dev/provider-diagnostics/stop")
        assert stopped.status_code == 200
        assert stopped.json()["status"] == "stopped"


def test_diagnostic_experience_routes_are_absent_in_production() -> None:
    client = TestClient(create_app(Settings(_env_file=None, app_env="production")))

    assert "/api/v1/dev/provider-diagnostics/start" not in client.app.openapi()["paths"]
    assert client.post("/api/v1/dev/provider-diagnostics/start").status_code == 404


def test_diagnostic_experience_setting_is_rejected_in_production() -> None:
    with pytest.raises(ValueError, match="allowed only in development/test"):
        Settings(
            _env_file=None,
            app_env="production",
            tiktok_live_diagnostics_enabled=True,
        )


def test_provider_startup_activates_diagnostics_before_listener_and_stops_it_on_shutdown() -> None:
    clients: list[FakeTikTokClient] = []
    adapter = TikTokLiveAdapter(
        FakeIngestionService(),
        enabled=True,
        username="streamer",
        bindings=make_bindings(clients),
    )
    settings = Settings(
        _env_file=None,
        app_env="test",
        tiktok_live_enabled=True,
        tiktok_live_username="streamer",
        tiktok_live_diagnostics_enabled=True,
    )
    app = create_app(settings, tiktok_live_adapter=adapter)

    with TestClient(app) as client:
        assert app.state.engine_runtime.state()["active_experience"] == "provider-diagnostics"
        assert clients[0].started is True
        assert client.get("/api/v1/providers/tiktok").json()["status"] == "starting"

    assert clients[0].disconnected is True
    assert adapter.snapshot()["status"] == "stopped"
    assert app.state.engine_runtime.state()["active_experience"] is None


def test_provider_does_not_start_without_an_active_or_opted_in_diagnostic_experience() -> None:
    clients: list[FakeTikTokClient] = []
    adapter = TikTokLiveAdapter(
        FakeIngestionService(),
        enabled=True,
        username="streamer",
        bindings=make_bindings(clients),
    )
    settings = Settings(
        _env_file=None,
        app_env="test",
        tiktok_live_enabled=True,
        tiktok_live_username="streamer",
    )
    app = create_app(settings, tiktok_live_adapter=adapter)

    with pytest.raises(RuntimeError, match="no Experience is active"):
        with TestClient(app):
            pytest.fail("Startup should require an explicitly active Experience")

    assert clients == []


def test_fake_provider_event_traverses_adapter_runtime_diagnostics_and_websocket() -> None:
    from backend.app.application.event_ingestion import (
        EventIngestionService,
        InMemoryEventDeduplicationStore,
    )
    from backend.app.realtime.realtime_manager import RealtimeManager
    from backend.app.runtime.engine_runtime import EngineRuntime

    clients: list[FakeTikTokClient] = []
    runtime = EngineRuntime()
    realtime = RealtimeManager()
    store = InMemoryEventDeduplicationStore()
    ingestion = EventIngestionService(runtime, store)
    adapter = TikTokLiveAdapter(
        ingestion,
        enabled=True,
        username="streamer",
        bindings=make_bindings(clients),
    )
    settings = Settings(
        _env_file=None,
        app_env="test",
        tiktok_live_enabled=True,
        tiktok_live_username="streamer",
        tiktok_live_diagnostics_enabled=True,
    )
    app = create_app(
        settings,
        runtime=runtime,
        realtime_manager=realtime,
        event_deduplication_store=store,
        tiktok_live_adapter=adapter,
    )

    with TestClient(app) as client:
        with client.websocket_connect("/ws/events") as websocket:
            assert websocket.receive_json()["type"] == "SYSTEM_READY"
            assert client.portal is not None
            client.portal.call(
                clients[0].emit,
                FakeEventTypes.CommentEvent,
                SimpleNamespace(
                    comment="never echo the original comment",
                    user=SimpleNamespace(unique_id="viewer", nickname="Private name"),
                ),
            )
            message = websocket.receive_json()
            state = client.portal.call(runtime.manager.get_state)

            assert message["type"] == "PROVIDER_EVENT_RECEIVED"
            assert message["experience"] == "provider-diagnostics"
            assert message["data"]["event_type"] == "COMMENT"
            assert message["data"]["text_length"] == len("never echo the original comment")
            assert "never echo the original comment" not in str(message)
            assert state["total_events"] == 1
            assert state["events_by_type"] == {"COMMENT": 1}
            assert adapter.snapshot()["processed_events"] == 1

    assert runtime.state()["active_experience"] is None


def test_fake_provider_event_persists_and_deduplicates_through_sqlite(tmp_path):
    from sqlalchemy import select

    from backend.app.application.event_ingestion import EventIngestionService
    from backend.app.persistence.database import (
        create_database_engine,
        create_session_factory,
    )
    from backend.app.persistence.event_repository import SqlAlchemyEventStore
    from backend.app.persistence.models import Base, LiveEventRecord
    from backend.app.realtime.realtime_manager import RealtimeManager
    from backend.app.runtime.engine_runtime import EngineRuntime

    database_path = (tmp_path / "provider-integration.db").as_posix()
    engine = create_database_engine(f"sqlite:///{database_path}")
    Base.metadata.create_all(engine)
    session_factory = create_session_factory(engine)
    store = SqlAlchemyEventStore(session_factory)

    clients: list[FakeTikTokClient] = []
    realtime = RealtimeManager()
    runtime = EngineRuntime(output_publisher=realtime)
    ingestion = EventIngestionService(runtime, store)

    adapter = TikTokLiveAdapter(
        ingestion,
        enabled=True,
        username="streamer",
        bindings=make_bindings(clients),
    )
    settings = Settings(
        _env_file=None,
        app_env="test",
        tiktok_live_enabled=True,
        tiktok_live_username="streamer",
        tiktok_live_diagnostics_enabled=True,
    )
    app = create_app(
        settings,
        runtime=runtime,
        realtime_manager=realtime,
        event_deduplication_store=store,
        tiktok_live_adapter=adapter,
    )

    comment = "comment must stay private"
    username = "viewer_42"
    provider_event = SimpleNamespace(
        comment=comment,
        common=SimpleNamespace(msg_id="tiktok-message-001"),
        user=SimpleNamespace(
            id=42,
            unique_id=username,
            nickname="Private Viewer",
        ),
    )

    try:
        with TestClient(app) as client:
            with client.websocket_connect("/ws/events") as websocket:
                assert websocket.receive_json()["type"] == "SYSTEM_READY"
                assert client.portal is not None

                client.portal.call(
                    clients[0].emit,
                    FakeEventTypes.CommentEvent,
                    provider_event,
                )
                output = websocket.receive_json()

                assert output["type"] == "PROVIDER_EVENT_RECEIVED"
                assert output["data"]["event_type"] == "COMMENT"
                assert output["data"]["text_length"] == len(comment)
                assert comment not in str(output)
                assert username not in str(output)
                assert "Private Viewer" not in str(output)

                # The same external identity must not dispatch or publish twice.
                client.portal.call(
                    clients[0].emit,
                    FakeEventTypes.CommentEvent,
                    provider_event,
                )

                status = adapter.snapshot()
                assert status["processed_events"] == 1
                assert status["duplicate_events"] == 1

        with session_factory() as session:
            records = session.scalars(select(LiveEventRecord)).all()

            assert len(records) == 1
            record = records[0]
            assert record.provider == "tiktok"
            assert record.event_type == "COMMENT"
            assert record.provider_event_id == "tiktok-message-001"
            assert record.processing_status == "PROCESSED"
            assert record.payload == {"text": comment}
            assert record.viewer_data == {
                "provider_user_id": "42",
                "username": username,
            }
    finally:
        engine.dispose()
