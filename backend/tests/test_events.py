"""Unit tests for domain contracts; no API, ORM, provider SDK, or network required."""

from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID

import pytest
from pydantic import ValidationError

from backend.app.domain.events import (
    MAX_JSON_NESTING_DEPTH,
    MAX_JSON_OBJECT_BYTES,
    EventProvider,
    EventType,
    LiveEvent,
    OutputEvent,
    Viewer,
)


def make_live_event(**overrides: object) -> LiveEvent:
    values: dict[str, object] = {
        "type": EventType.COMMENT,
        "provider": EventProvider.SIMULATOR,
        "occurred_at": datetime(2026, 10, 15, 20, 0, tzinfo=UTC),
        "payload": {"text": "teste"},
    }
    values.update(overrides)
    return LiveEvent.model_validate(values)


def test_string_enums_serialize_as_their_contract_values() -> None:
    assert str(EventType.COMMENT) == "COMMENT"
    assert str(EventProvider.SIMULATOR) == "simulator"


def test_event_type_contains_the_planned_normalized_types() -> None:
    assert {event_type.value for event_type in EventType} == {
        "COMMENT",
        "GIFT",
        "LIKE",
        "FOLLOW",
        "SHARE",
        "JOIN",
        "CONNECT",
        "DISCONNECT",
    }


def test_live_event_generates_an_internal_uuid_and_utc_received_time() -> None:
    event = make_live_event()

    assert isinstance(event.event_id, UUID)
    assert event.received_at.tzinfo is UTC
    assert event.provider is EventProvider.SIMULATOR


def test_live_event_does_not_reuse_generated_event_ids() -> None:
    first = make_live_event()
    second = make_live_event()

    assert first.event_id != second.event_id


def test_live_event_normalizes_aware_timestamp_to_utc() -> None:
    offset = timezone(timedelta(hours=-3))
    event = make_live_event(occurred_at=datetime(2026, 10, 15, 20, 0, tzinfo=offset))

    assert event.occurred_at == datetime(2026, 10, 15, 23, 0, tzinfo=UTC)
    assert event.occurred_at.tzinfo is UTC


def test_live_event_rejects_naive_occurred_at() -> None:
    with pytest.raises(ValidationError, match="timestamp must include a timezone"):
        make_live_event(occurred_at=datetime(2026, 10, 15, 20, 0))


def test_live_event_rejects_naive_received_at() -> None:
    with pytest.raises(ValidationError, match="timestamp must include a timezone"):
        make_live_event(received_at=datetime(2026, 10, 15, 20, 0))


def test_live_event_rejects_an_unregistered_provider() -> None:
    with pytest.raises(ValidationError):
        make_live_event(provider="arbitrary-provider")


def test_live_event_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError, match="extra_forbidden"):
        make_live_event(world_id="world001")


def test_live_event_accepts_gift_without_special_casing_rose() -> None:
    event = make_live_event(
        type=EventType.GIFT,
        payload={"gift_id": "5655", "gift_name": "Rose", "quantity": 1},
    )

    assert event.type is EventType.GIFT
    assert event.payload["gift_name"] == "Rose"
    assert "ROSE" not in EventType.__members__


def test_live_event_rejects_payload_above_encoded_size_limit() -> None:
    oversized_text = "x" * MAX_JSON_OBJECT_BYTES

    with pytest.raises(ValidationError, match="byte limit"):
        make_live_event(payload={"text": oversized_text})


def test_live_event_rejects_payload_above_nesting_limit() -> None:
    nested: object = "value"
    for _ in range(MAX_JSON_NESTING_DEPTH):
        nested = {"nested": nested}

    with pytest.raises(ValidationError, match="nesting-depth limit"):
        make_live_event(payload={"data": nested})


def test_live_event_rejects_non_json_payload_values() -> None:
    with pytest.raises(ValidationError):
        make_live_event(payload={"not_json": object()})


def test_viewer_trims_text_and_accepts_partial_identity() -> None:
    viewer = Viewer(provider_user_id=" 123 ", display_name=" Maria ")

    assert viewer.provider_user_id == "123"
    assert viewer.display_name == "Maria"
    assert viewer.username is None


def test_viewer_requires_at_least_one_identity_or_presentation_field() -> None:
    with pytest.raises(ValidationError, match="at least one"):
        Viewer()


def test_viewer_rejects_non_http_avatar_urls() -> None:
    with pytest.raises(ValidationError):
        Viewer(username="maria", avatar_url="javascript:alert(1)")


def test_contracts_are_immutable_at_the_model_field_level() -> None:
    event = make_live_event()

    with pytest.raises(ValidationError, match="frozen_instance"):
        event.type = EventType.GIFT  # type: ignore[misc]


def test_output_event_generates_versioned_envelope_and_uuid() -> None:
    output = OutputEvent(
        type="GAME_EVENT",
        experience="test-experience",
        data={"action": "display_message", "text": "Olá"},
    )

    assert output.protocol_version == 1
    assert isinstance(output.message_id, UUID)
    assert output.occurred_at.tzinfo is UTC
    assert output.model_dump(mode="json")["experience"] == "test-experience"


def test_output_event_normalizes_timestamp_to_utc() -> None:
    offset = timezone(timedelta(hours=-3))
    output = OutputEvent(
        type="GAME_EVENT",
        experience="test-experience",
        occurred_at=datetime(2026, 10, 15, 20, 0, tzinfo=offset),
    )

    assert output.occurred_at == datetime(2026, 10, 15, 23, 0, tzinfo=UTC)


def test_output_event_rejects_naive_timestamp() -> None:
    with pytest.raises(ValidationError, match="timestamp must include a timezone"):
        OutputEvent(
            type="GAME_EVENT",
            experience="test-experience",
            occurred_at=datetime(2026, 10, 15, 20, 0),
        )


@pytest.mark.parametrize("invalid_type", ["game_event", "1_EVENT", "A", "GAME-EVENT"])
def test_output_event_rejects_invalid_message_type(invalid_type: str) -> None:
    with pytest.raises(ValidationError):
        OutputEvent(type=invalid_type, experience="test-experience")


@pytest.mark.parametrize("invalid_slug", ["Test", "two words", "a--b", "../admin", ""])
def test_output_event_rejects_invalid_experience_slug(invalid_slug: str) -> None:
    with pytest.raises(ValidationError):
        OutputEvent(type="GAME_EVENT", experience=invalid_slug)


def test_output_event_rejects_unsupported_protocol_version() -> None:
    with pytest.raises(ValidationError):
        OutputEvent(
            protocol_version=2,
            type="GAME_EVENT",
            experience="test-experience",
        )


def test_output_event_rejects_oversized_data() -> None:
    with pytest.raises(ValidationError, match="byte limit"):
        OutputEvent(
            type="GAME_EVENT",
            experience="test-experience",
            data={"message": "x" * MAX_JSON_OBJECT_BYTES},
        )
