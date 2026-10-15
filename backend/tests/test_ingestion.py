"""Dev Event API and central ingestion tests with in-process fakes only."""

from datetime import UTC, datetime

from fastapi.testclient import TestClient

from backend.app.config import Settings
from backend.app.domain.events import EventProvider, EventType, LiveEvent, OutputEvent
from backend.app.main import create_app
from backend.app.runtime.engine_runtime import EngineRuntime
from backend.app.runtime.experience import ExperienceContext
from backend.app.runtime.experience_loader import ExperienceLoader


class FakeExperience:
    slug = "test-game"
    name = "Test Game"
    version = "0.1.0"

    def __init__(self) -> None:
        self.events: list[LiveEvent] = []
        self.should_fail = False
        self.outputs = [
            OutputEvent(
                type="GAME_EVENT",
                experience=self.slug,
                data={"action": "display_message", "text": "event received"},
            )
        ]

    async def start(self, context: ExperienceContext) -> None:
        assert context.experience_slug == self.slug

    async def stop(self, context: ExperienceContext) -> None:
        return None

    async def handle_event(
        self,
        event: LiveEvent,
        context: ExperienceContext,
    ) -> list[OutputEvent]:
        if self.should_fail:
            raise RuntimeError("simulated Experience failure")
        self.events.append(event)
        return list(self.outputs)

    async def get_state(self, context: ExperienceContext) -> dict[str, object]:
        return {"received_events": len(self.events)}

    async def health(self, context: ExperienceContext) -> dict[str, object]:
        return {"status": "ok"}


def make_app(
    environment: str = "test",
) -> tuple[TestClient, EngineRuntime, FakeExperience]:
    experience = FakeExperience()
    loader = ExperienceLoader()
    loader.register(
        slug=experience.slug,
        name=experience.name,
        version=experience.version,
        factory=lambda: experience,
    )
    runtime = EngineRuntime(loader)
    app = create_app(Settings(_env_file=None, app_env=environment), runtime=runtime)
    return TestClient(app), runtime, experience


def comment_payload(provider_event_id: str = "comment-001") -> dict[str, object]:
    return {
        "type": "COMMENT",
        "provider_event_id": provider_event_id,
        "session_id": "sim-session-001",
        "viewer": {
            "provider_user_id": "sim-user-001",
            "username": "maria",
            "display_name": "Maria",
        },
        "payload": {"text": "mensagem de teste"},
    }


def test_dev_event_api_processes_event_and_publishes_output_to_websocket() -> None:
    client, runtime, experience = make_app()

    with client:
        assert client.portal is not None
        client.portal.call(runtime.start_experience, "test-game")
        with client.websocket_connect("/ws/events") as websocket:
            assert websocket.receive_json()["type"] == "SYSTEM_READY"

            response = client.post("/api/v1/dev/events", json=comment_payload())
            assert response.status_code == 200
            result = response.json()
            assert result["status"] == "processed"
            assert result["delivered_clients"] == 1
            assert result["outputs"][0]["type"] == "GAME_EVENT"
            assert result["outputs"][0]["experience"] == "test-game"

            received = websocket.receive_json()
            assert received["type"] == "GAME_EVENT"
            assert received["data"]["text"] == "event received"

        client.portal.call(runtime.stop_experience)

    assert len(experience.events) == 1
    assert experience.events[0].provider is EventProvider.SIMULATOR
    assert experience.events[0].type is EventType.COMMENT
    assert experience.events[0].payload["text"] == "mensagem de teste"


def test_duplicate_provider_event_id_returns_duplicate_without_second_dispatch() -> None:
    client, runtime, experience = make_app()

    with client:
        assert client.portal is not None
        client.portal.call(runtime.start_experience, "test-game")

        first = client.post("/api/v1/dev/events", json=comment_payload("same-id"))
        second = client.post("/api/v1/dev/events", json=comment_payload("same-id"))

        assert first.status_code == second.status_code == 200
        assert first.json()["status"] == "processed"
        assert second.json()["status"] == "duplicate"
        assert second.json()["duplicate_of_event_id"] == first.json()["event_id"]
        assert second.json()["outputs"] == []
        assert len(experience.events) == 1

        client.portal.call(runtime.stop_experience)


def test_events_without_provider_event_id_are_not_deduplicated() -> None:
    client, runtime, experience = make_app()
    payload = comment_payload()
    payload.pop("provider_event_id")

    with client:
        assert client.portal is not None
        client.portal.call(runtime.start_experience, "test-game")
        first = client.post("/api/v1/dev/events", json=payload)
        second = client.post("/api/v1/dev/events", json=payload)
        assert first.json()["status"] == "processed"
        assert second.json()["status"] == "processed"
        assert len(experience.events) == 2
        client.portal.call(runtime.stop_experience)


def test_invalid_request_uses_stable_error_envelope_and_rejects_provider_override() -> None:
    client, _, _ = make_app()
    response = client.post(
        "/api/v1/dev/events",
        json={**comment_payload(), "provider": "tiktok"},
    )

    assert response.status_code == 422
    assert response.json() == {
        "error": {
            "code": "INVALID_REQUEST",
            "message": "The request does not match the expected schema or validation rules.",
        }
    }


def test_comment_text_is_required_and_payload_size_is_limited() -> None:
    client, _, _ = make_app()
    missing_text = client.post(
        "/api/v1/dev/events",
        json={"type": "COMMENT", "payload": {}},
    )
    oversized = client.post(
        "/api/v1/dev/events",
        json={"type": "GIFT", "payload": {"text": "x" * 16_384}},
    )

    assert missing_text.status_code == 422
    assert oversized.status_code == 422
    assert missing_text.json()["error"]["code"] == "INVALID_REQUEST"
    assert oversized.json()["error"]["code"] == "INVALID_REQUEST"


def test_gift_quantity_and_like_count_must_be_bounded_integers() -> None:
    client, _, _ = make_app()
    invalid_gift = client.post(
        "/api/v1/dev/events",
        json={"type": "GIFT", "payload": {"gift_name": "Rose", "quantity": True}},
    )
    invalid_like = client.post(
        "/api/v1/dev/events",
        json={"type": "LIKE", "payload": {"count": 0}},
    )

    assert invalid_gift.status_code == 422
    assert invalid_like.status_code == 422


def test_dispatch_failure_returns_generic_error_and_releases_dedupe_reservation() -> None:
    client, runtime, experience = make_app()
    experience.should_fail = True

    with client:
        assert client.portal is not None
        client.portal.call(runtime.start_experience, "test-game")
        first = client.post("/api/v1/dev/events", json=comment_payload("retry-after-failure"))
        assert first.status_code == 500
        assert first.json() == {
            "error": {
                "code": "EVENT_PROCESSING_FAILED",
                "message": "The event could not be processed.",
            }
        }

        experience.should_fail = False
        retry = client.post("/api/v1/dev/events", json=comment_payload("retry-after-failure"))
        assert retry.status_code == 200
        assert retry.json()["status"] == "processed"
        assert len(experience.events) == 1
        client.portal.call(runtime.stop_experience)


def test_request_without_active_experience_returns_conflict_and_can_be_retried() -> None:
    client, runtime, experience = make_app()

    with client:
        first = client.post("/api/v1/dev/events", json=comment_payload("before-start"))
        assert first.status_code == 409
        assert first.json()["error"]["code"] == "NO_ACTIVE_EXPERIENCE"

        assert client.portal is not None
        client.portal.call(runtime.start_experience, "test-game")
        retry = client.post("/api/v1/dev/events", json=comment_payload("before-start"))
        assert retry.status_code == 200
        assert retry.json()["status"] == "processed"
        assert len(experience.events) == 1
        client.portal.call(runtime.stop_experience)


def test_dev_events_route_is_not_registered_in_production() -> None:
    client, _, _ = make_app(environment="production")

    assert "/api/v1/dev/events" not in client.app.openapi()["paths"]
    response = client.post("/api/v1/dev/events", json=comment_payload())
    assert response.status_code == 404


def test_dev_request_sets_server_owned_event_identity_and_timestamp() -> None:
    client, runtime, experience = make_app()
    payload = {
        "type": "GIFT",
        "provider_event_id": "gift-001",
        "payload": {"gift_id": "5655", "gift_name": "Rose", "quantity": 1},
        "occurred_at": datetime(2026, 10, 15, 20, 0, tzinfo=UTC).isoformat(),
    }

    with client:
        assert client.portal is not None
        client.portal.call(runtime.start_experience, "test-game")
        response = client.post("/api/v1/dev/events", json=payload)
        assert response.status_code == 200
        received = experience.events[0]
        assert received.provider is EventProvider.SIMULATOR
        assert received.event_id is not None
        assert received.received_at.tzinfo is UTC
        assert received.type is EventType.GIFT
        assert received.payload["gift_name"] == "Rose"
        client.portal.call(runtime.stop_experience)
