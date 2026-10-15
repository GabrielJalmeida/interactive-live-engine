"""Runtime and Experience contract tests; no provider, database, or LIVE required."""

import asyncio
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from backend.app.config import Settings
from backend.app.domain.events import EventProvider, EventType, LiveEvent, OutputEvent
from backend.app.main import create_app
from backend.app.runtime.engine_runtime import EngineRuntime
from backend.app.runtime.experience import ExperienceContext
from backend.app.runtime.experience_loader import (
    ExperienceLoader,
    ExperienceRegistrationError,
    InvalidExperienceDefinitionError,
    UnknownExperienceError,
)
from backend.app.runtime.experience_manager import (
    ExperienceLifecycleError,
    InvalidExperienceOutputError,
    NoActiveExperienceError,
)


class FakeExperience:
    slug = "test-game"
    name = "Test Game"
    version = "0.1.0"

    def __init__(self) -> None:
        self.started = False
        self.stopped = False
        self.events: list[LiveEvent] = []
        self.fail_on_start = False
        self.outputs: list[OutputEvent] = []

    async def start(self, context: ExperienceContext) -> None:
        if self.fail_on_start:
            raise RuntimeError("start failed")
        assert context.experience_slug == self.slug
        self.started = True

    async def stop(self, context: ExperienceContext) -> None:
        self.stopped = True

    async def handle_event(self, event: LiveEvent, context: ExperienceContext) -> list[OutputEvent]:
        self.events.append(event)
        return list(self.outputs)

    async def get_state(self, context: ExperienceContext) -> dict[str, object]:
        return {"received_events": len(self.events)}

    async def health(self, context: ExperienceContext) -> dict[str, object]:
        return {"status": "ok", "slug": context.experience_slug}


def make_event() -> LiveEvent:
    return LiveEvent(
        type=EventType.COMMENT,
        provider=EventProvider.SIMULATOR,
        occurred_at=datetime(2026, 10, 15, 20, 0, tzinfo=UTC),
        payload={"text": "hello"},
    )


def make_runtime(factory=FakeExperience) -> tuple[EngineRuntime, ExperienceLoader]:
    loader = ExperienceLoader()
    loader.register(slug="test-game", name="Test Game", version="0.1.0", factory=factory)
    return EngineRuntime(loader), loader


def test_loader_lists_metadata_in_deterministic_order() -> None:
    loader = ExperienceLoader()
    loader.register(slug="z-game", name="Z Game", version="1.0", factory=lambda: FakeExperience())
    loader.register(slug="a-game", name="A Game", version="1.0", factory=lambda: FakeExperience())

    assert [entry.slug for entry in loader.list_experiences()] == ["a-game", "z-game"]


def test_loader_rejects_duplicate_slug() -> None:
    loader = ExperienceLoader()
    kwargs = {"slug": "test-game", "name": "Test Game", "version": "1.0", "factory": FakeExperience}
    loader.register(**kwargs)

    with pytest.raises(ExperienceRegistrationError, match="already registered"):
        loader.register(**kwargs)


def test_loader_rejects_invalid_slug() -> None:
    loader = ExperienceLoader()
    with pytest.raises(ValueError):
        loader.register(slug="../admin", name="Test Game", version="1.0", factory=FakeExperience)


def test_loader_requires_instance_metadata_to_match_registration() -> None:
    class MismatchedExperience(FakeExperience):
        slug = "different-game"

    _, loader = make_runtime(MismatchedExperience)
    with pytest.raises(InvalidExperienceDefinitionError, match="mismatched metadata"):
        loader.create("test-game")


def test_loader_rejects_unknown_slug() -> None:
    _, loader = make_runtime()
    with pytest.raises(UnknownExperienceError, match="not registered"):
        loader.create("missing-game")


def test_runtime_requires_active_experience_for_dispatch() -> None:
    runtime, _ = make_runtime()
    with pytest.raises(NoActiveExperienceError):
        asyncio.run(runtime.dispatch(make_event()))


def test_runtime_starts_dispatches_outputs_and_stops_experience() -> None:
    experience = FakeExperience()
    experience.outputs = [OutputEvent(type="GAME_EVENT", experience="test-game", data={"ok": True})]
    runtime, _ = make_runtime(lambda: experience)

    async def scenario() -> None:
        metadata = await runtime.start_experience("test-game", config={"difficulty": "easy"})
        outputs = await runtime.dispatch(make_event())
        state = await runtime.manager.get_state()
        health = await runtime.health()
        stopped = await runtime.stop_experience()
        stopped_again = await runtime.stop_experience()

        assert metadata.slug == "test-game"
        assert len(outputs) == 1 and outputs[0].type == "GAME_EVENT"
        assert state == {"received_events": 1}
        assert health["status"] == "ok"
        assert stopped is True
        assert stopped_again is False

    asyncio.run(scenario())
    assert experience.started is True
    assert experience.stopped is True
    assert runtime.state() == {
        "runtime": "stopped",
        "active_experience": None,
        "experience_status": "stopped",
    }


def test_runtime_rejects_starting_second_experience_while_one_is_running() -> None:
    runtime, _ = make_runtime()

    async def scenario() -> None:
        await runtime.start_experience("test-game")
        with pytest.raises(ExperienceLifecycleError, match="while Runtime status"):
            await runtime.start_experience("test-game")

    asyncio.run(scenario())


def test_runtime_cleans_up_and_marks_failed_when_start_raises() -> None:
    experience = FakeExperience()
    experience.fail_on_start = True
    runtime, _ = make_runtime(lambda: experience)

    async def scenario() -> None:
        with pytest.raises(RuntimeError, match="start failed"):
            await runtime.start_experience("test-game")

    asyncio.run(scenario())
    assert experience.stopped is True
    assert runtime.state()["runtime"] == "failed"
    assert runtime.state()["active_experience"] is None


def test_runtime_rejects_output_for_different_experience() -> None:
    experience = FakeExperience()
    experience.outputs = [OutputEvent(type="GAME_EVENT", experience="other-game")]
    runtime, _ = make_runtime(lambda: experience)

    async def scenario() -> None:
        await runtime.start_experience("test-game")
        with pytest.raises(InvalidExperienceOutputError, match="expected 'test-game'"):
            await runtime.dispatch(make_event())

    asyncio.run(scenario())


def test_runtime_rejects_non_output_items_from_experience() -> None:
    experience = FakeExperience()

    async def invalid_handler(event: LiveEvent, context: ExperienceContext) -> list[OutputEvent]:
        return ["not an output"]  # type: ignore[list-item]

    experience.handle_event = invalid_handler  # type: ignore[method-assign]
    runtime, _ = make_runtime(lambda: experience)

    async def scenario() -> None:
        await runtime.start_experience("test-game")
        with pytest.raises(InvalidExperienceOutputError, match="not an OutputEvent"):
            await runtime.dispatch(make_event())

    asyncio.run(scenario())


def test_engine_state_api_does_not_expose_gameplay_state() -> None:
    runtime, _ = make_runtime()
    client = TestClient(create_app(Settings(_env_file=None, app_env="test"), runtime=runtime))

    response = client.get("/api/v1/engine/state")

    assert response.status_code == 200
    assert response.json() == {
        "runtime": "stopped",
        "active_experience": None,
        "experience_status": "stopped",
    }


def test_experiences_api_lists_only_explicitly_registered_factories() -> None:
    runtime, _ = make_runtime()
    client = TestClient(create_app(Settings(_env_file=None, app_env="test"), runtime=runtime))

    response = client.get("/api/v1/experiences")

    assert response.status_code == 200
    assert response.json() == [{"slug": "test-game", "name": "Test Game", "version": "0.1.0"}]


def test_default_app_has_no_bundled_game_experience() -> None:
    client = TestClient(create_app(Settings(_env_file=None, app_env="test")))

    assert client.get("/api/v1/experiences").json() == []
