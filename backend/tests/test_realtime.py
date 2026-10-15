"""Realtime manager, WebSocket route, and Runtime-to-client integration tests."""

import asyncio
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from backend.app.config import Settings
from backend.app.domain.events import EventProvider, EventType, LiveEvent, OutputEvent
from backend.app.main import create_app
from backend.app.realtime.realtime_manager import RealtimeManager
from backend.app.runtime.engine_runtime import EngineRuntime
from backend.app.runtime.experience import ExperienceContext
from backend.app.runtime.experience_loader import ExperienceLoader


class FakeSocket:
    """Minimal async socket double for deterministic send/failure tests."""

    def __init__(
        self,
        *,
        fail_after_ready: bool = False,
        delay_after_ready: float = 0,
    ) -> None:
        self.accepted = False
        self.messages: list[dict[str, object]] = []
        self.fail_after_ready = fail_after_ready
        self.delay_after_ready = delay_after_ready

    async def accept(self) -> None:
        self.accepted = True

    async def send_json(self, payload: dict[str, object]) -> None:
        if payload.get("type") != "SYSTEM_READY":
            if self.delay_after_ready:
                await asyncio.sleep(self.delay_after_ready)
            if self.fail_after_ready:
                raise RuntimeError("simulated socket failure")
        self.messages.append(payload)


class FakeExperience:
    slug = "test-game"
    name = "Test Game"
    version = "0.1.0"

    def __init__(self) -> None:
        self.outputs: list[OutputEvent] = []
        self.received: list[LiveEvent] = []

    async def start(self, context: ExperienceContext) -> None:
        return None

    async def stop(self, context: ExperienceContext) -> None:
        return None

    async def handle_event(
        self,
        event: LiveEvent,
        context: ExperienceContext,
    ) -> list[OutputEvent]:
        self.received.append(event)
        return list(self.outputs)

    async def get_state(self, context: ExperienceContext) -> dict[str, object]:
        return {"received_events": len(self.received)}

    async def health(self, context: ExperienceContext) -> dict[str, object]:
        return {"status": "ok"}


def make_output() -> OutputEvent:
    return OutputEvent(
        type="GAME_EVENT",
        experience="test-game",
        data={"action": "display_message", "text": "Olá LIVE"},
    )


def make_event() -> LiveEvent:
    return LiveEvent(
        type=EventType.COMMENT,
        provider=EventProvider.SIMULATOR,
        occurred_at=datetime(2026, 10, 15, 20, 0, tzinfo=UTC),
        payload={"text": "teste"},
    )


def make_runtime_with_experience(
    *,
    output_publisher: RealtimeManager | None = None,
) -> tuple[EngineRuntime, FakeExperience]:
    experience = FakeExperience()
    loader = ExperienceLoader()
    loader.register(
        slug=experience.slug,
        name=experience.name,
        version=experience.version,
        factory=lambda: experience,
    )
    return EngineRuntime(loader, output_publisher=output_publisher), experience


def test_manager_broadcasts_output_to_all_connected_clients() -> None:
    async def scenario() -> None:
        manager = RealtimeManager()
        first = FakeSocket()
        second = FakeSocket()
        assert await manager.connect(first) is True
        assert await manager.connect(second) is True

        delivered = await manager.publish(make_output())

        assert delivered == 2
        assert manager.connection_count == 2
        assert first.messages[0]["type"] == "SYSTEM_READY"
        assert first.messages[1]["type"] == "GAME_EVENT"
        assert second.messages[1]["data"] == {"action": "display_message", "text": "Olá LIVE"}

    asyncio.run(scenario())


def test_failed_client_is_removed_without_interrupting_other_clients() -> None:
    async def scenario() -> None:
        manager = RealtimeManager()
        broken = FakeSocket(fail_after_ready=True)
        healthy = FakeSocket()
        await manager.connect(broken)
        await manager.connect(healthy)

        delivered = await manager.publish(make_output())

        assert delivered == 1
        assert [message["type"] for message in healthy.messages] == ["SYSTEM_READY", "GAME_EVENT"]
        assert manager.connection_count == 1

    asyncio.run(scenario())


def test_slow_client_timeout_does_not_prevent_healthy_delivery() -> None:
    async def scenario() -> None:
        manager = RealtimeManager(send_timeout_seconds=0.02)
        slow = FakeSocket(delay_after_ready=0.2)
        healthy = FakeSocket()
        await manager.connect(slow)
        await manager.connect(healthy)

        delivered = await asyncio.wait_for(manager.publish(make_output()), timeout=0.15)

        assert delivered == 1
        assert healthy.messages[-1]["type"] == "GAME_EVENT"
        assert manager.connection_count == 1

    asyncio.run(scenario())


def test_disconnect_is_idempotent_and_empty_broadcast_is_noop() -> None:
    async def scenario() -> None:
        manager = RealtimeManager()
        socket = FakeSocket()
        assert await manager.publish(make_output()) == 0
        await manager.connect(socket)
        await manager.disconnect(socket)
        await manager.disconnect(socket)
        assert manager.connection_count == 0
        assert await manager.publish(make_output()) == 0

    asyncio.run(scenario())


def test_manager_rejects_non_output_messages() -> None:
    async def scenario() -> None:
        manager = RealtimeManager()
        with pytest.raises(TypeError, match="requires an OutputEvent"):
            await manager.publish({"type": "GAME_EVENT"})  # type: ignore[arg-type]

    asyncio.run(scenario())


def test_websocket_sends_system_ready_and_runtime_output_to_browser_client() -> None:
    runtime, experience = make_runtime_with_experience()
    app = create_app(Settings(_env_file=None, app_env="test"), runtime=runtime)
    experience.outputs = [make_output()]

    with TestClient(app) as client:
        assert client.portal is not None
        client.portal.call(runtime.start_experience, "test-game")
        with client.websocket_connect("/ws/events") as websocket:
            ready = websocket.receive_json()
            assert ready["protocol_version"] == 1
            assert ready["type"] == "SYSTEM_READY"
            assert "occurred_at" in ready

            outputs = client.portal.call(runtime.dispatch, make_event())
            delivered = client.portal.call(runtime.publish, outputs)
            received = websocket.receive_json()

            assert delivered == 1
            assert received["type"] == "GAME_EVENT"
            assert received["experience"] == "test-game"
            assert received["data"] == {"action": "display_message", "text": "Olá LIVE"}

        client.portal.call(runtime.stop_experience)

    assert experience.received[0].payload["text"] == "teste"


def test_websocket_rejects_client_application_messages() -> None:
    app = create_app(Settings(_env_file=None, app_env="test"))
    with TestClient(app) as client:
        with client.websocket_connect("/ws/events") as websocket:
            assert websocket.receive_json()["type"] == "SYSTEM_READY"
            websocket.send_text('{"command":"do-something"}')
            with pytest.raises(WebSocketDisconnect) as disconnect:
                websocket.receive_text()
            assert disconnect.value.code == 1008


def test_websocket_same_origin_policy_rejects_cross_origin_browser_handshake() -> None:
    app = create_app(Settings(_env_file=None, app_env="test"))
    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect) as denied:
            with client.websocket_connect(
                "/ws/events",
                headers={"origin": "http://evil.example"},
            ):
                pass
        assert denied.value.code == 1008


def test_websocket_accepts_a_same_origin_browser_handshake() -> None:
    app = create_app(Settings(_env_file=None, app_env="test"))
    with TestClient(app) as client:
        with client.websocket_connect(
            "/ws/events",
            headers={"origin": "http://testserver"},
        ) as websocket:
            assert websocket.receive_json()["type"] == "SYSTEM_READY"


def test_realtime_harness_is_available_in_development_and_hidden_in_production() -> None:
    development = TestClient(create_app(Settings(_env_file=None, app_env="development")))
    response = development.get("/dev/realtime-harness")
    assert response.status_code == 200
    assert "Realtime Harness" in response.text

    production = TestClient(create_app(Settings(_env_file=None, app_env="production")))
    assert production.get("/dev/realtime-harness").status_code == 404
