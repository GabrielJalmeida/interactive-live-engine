"""TikTokLive listener and provider-to-domain event normalization.

The third-party SDK is imported lazily, only when the provider is explicitly enabled.
Tests inject fake bindings and never connect to a live stream.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, Protocol

from backend.app.domain.events import EventProvider, EventType, LiveEvent, Viewer, utc_now

ProviderStatus = Literal[
    "disabled", "stopped", "starting", "connected", "disconnected", "stopping", "failed"
]

EVENT_TYPES: tuple[EventType, ...] = (
    EventType.CONNECT,
    EventType.DISCONNECT,
    EventType.COMMENT,
    EventType.GIFT,
    EventType.LIKE,
    EventType.FOLLOW,
    EventType.SHARE,
    EventType.JOIN,
)


class TikTokLiveConfigurationError(RuntimeError):
    """Raised when the optional provider cannot be configured or imported."""


class EventIngestionPort(Protocol):
    """Application-level port used by external event sources."""

    async def ingest(self, event: LiveEvent) -> object: ...


class TikTokLiveClientProtocol(Protocol):
    """Small subset of the TikTokLive client API used by this adapter."""

    def add_listener(
        self, event_type: type[object], listener: Callable[[object], Awaitable[None]]
    ) -> object: ...

    async def start(self, *, fetch_live_check: bool = True) -> Any: ...

    async def disconnect(self, close_client: bool = False) -> None: ...


@dataclass(frozen=True, slots=True)
class TikTokLiveBindings:
    """SDK entry points, injectable to test the adapter without importing the SDK."""

    client_factory: Callable[..., TikTokLiveClientProtocol]
    event_types: Mapping[EventType, type[object]]


class TikTokLiveEventNormalizer:
    """Convert selected TikTokLive event objects into strict internal LiveEvent values."""

    def normalize(
        self,
        event_type: EventType,
        provider_event: object,
        *,
        session_id: str | None = None,
    ) -> LiveEvent | None:
        """Return one normalized event, or ``None`` for an unfinished gift streak update."""

        if event_type is EventType.GIFT and bool(getattr(provider_event, "streaking", False)):
            # A streak emits intermediate GiftEvents. Dispatch only its completed count so
            # one viewer action cannot repeatedly trigger gameplay while the streak grows.
            return None

        normalized_session_id = session_id
        payload: dict[str, Any]

        if event_type is EventType.CONNECT:
            room_id = _safe_scalar(getattr(provider_event, "room_id", None))
            if room_id is not None:
                normalized_session_id = str(room_id)
            payload = {"room_id": room_id} if room_id is not None else {}
        elif event_type is EventType.DISCONNECT:
            payload = {}
        elif event_type is EventType.COMMENT:
            comment = getattr(provider_event, "comment", None)
            if not isinstance(comment, str):
                # v3 exposes `content`; TikTokLive keeps `comment` as a compatibility alias.
                comment = getattr(provider_event, "content", None)
            if not isinstance(comment, str):
                raise ValueError("TikTokLive CommentEvent did not contain comment text")
            payload = {"text": comment}
        elif event_type is EventType.GIFT:
            gift = getattr(provider_event, "gift", None)
            if gift is None:
                raise ValueError("TikTokLive GiftEvent did not contain gift metadata")
            gift_name = _optional_text(getattr(gift, "name", None))
            gift_id = _safe_scalar(getattr(gift, "id", None))
            quantity = _positive_int(getattr(provider_event, "repeat_count", None), default=1)
            payload = {"quantity": quantity, "streaking": False}
            if gift_name is not None:
                payload["gift_name"] = gift_name
            if gift_id is not None:
                payload["gift_id"] = gift_id
        elif event_type is EventType.LIKE:
            count = _positive_int(getattr(provider_event, "count", None), default=1)
            total = _nonnegative_int(getattr(provider_event, "total", None))
            payload = {"count": count}
            if total is not None:
                payload["total"] = total
        elif event_type is EventType.FOLLOW:
            follow_count = _nonnegative_int(getattr(provider_event, "follow_count", None))
            payload = {"follow_count": follow_count} if follow_count is not None else {}
        elif event_type is EventType.SHARE:
            share_count = _nonnegative_int(getattr(provider_event, "share_count", None))
            users_joined = _nonnegative_int(getattr(provider_event, "users_joined", None))
            payload = {}
            if share_count is not None:
                payload["share_count"] = share_count
            if users_joined is not None:
                payload["users_joined"] = users_joined
        elif event_type is EventType.JOIN:
            member_count = _nonnegative_int(getattr(provider_event, "member_count", None))
            payload = {"member_count": member_count} if member_count is not None else {}
        else:  # pragma: no cover - guarded by EventType and EVENT_TYPES
            raise ValueError(f"Unsupported TikTokLive event type: {event_type}")

        provider_event_id = _provider_event_id(provider_event)
        viewer = _viewer_from_provider_event(provider_event)
        return LiveEvent(
            type=event_type,
            provider=EventProvider.TIKTOK,
            provider_event_id=provider_event_id,
            session_id=normalized_session_id,
            occurred_at=utc_now(),
            received_at=utc_now(),
            viewer=viewer,
            payload=payload,
        )


class TikTokLiveAdapter:
    """Manage TikTokLive client lifecycle and route normalized events into ingestion.

    ``enabled=False`` is safe in local development: the third-party SDK is not imported,
    no network connection is attempted, and the provider state reports ``disabled``.
    """

    def __init__(
        self,
        ingestion_service: EventIngestionPort,
        *,
        enabled: bool,
        username: str | None,
        bindings: TikTokLiveBindings | None = None,
        normalizer: TikTokLiveEventNormalizer | None = None,
        logger: logging.Logger | None = None,
        shutdown_timeout_seconds: float = 10.0,
    ) -> None:
        self._ingestion_service = ingestion_service
        self._enabled = enabled
        self._username = _clean_username(username)
        self._bindings = bindings
        self._normalizer = normalizer or TikTokLiveEventNormalizer()
        self._logger = logger or logging.getLogger("interactive_live_engine.providers.tiktok")
        self._shutdown_timeout_seconds = shutdown_timeout_seconds
        self._client: TikTokLiveClientProtocol | None = None
        self._connection_task: asyncio.Task[Any] | None = None
        self._monitor_task: asyncio.Task[None] | None = None
        self._session_id: str | None = None
        self._status: ProviderStatus = "disabled" if not enabled else "stopped"
        self._stopping = False
        self._lifecycle_lock = asyncio.Lock()
        self._provider_events_received = 0
        self._normalized_events = 0
        self._processed_events = 0
        self._duplicate_events = 0
        self._failed_events = 0
        self._ignored_gift_updates = 0
        self._last_event_at: str | None = None
        self._last_error_code: str | None = None

    @property
    def status(self) -> ProviderStatus:
        """Expose the provider lifecycle status without exposing SDK/client internals."""

        return self._status

    def snapshot(self) -> dict[str, bool | str | int | None]:
        """Return safe operational status and counters for the provider status endpoint."""

        return {
            "provider": "tiktok",
            "enabled": self._enabled,
            "status": self._status,
            "provider_events_received": self._provider_events_received,
            "normalized_events": self._normalized_events,
            "processed_events": self._processed_events,
            "duplicate_events": self._duplicate_events,
            "failed_events": self._failed_events,
            "ignored_gift_updates": self._ignored_gift_updates,
            "last_event_at": self._last_event_at,
            "last_error_code": self._last_error_code,
        }

    async def start(self) -> None:
        """Start the provider connection; requires an enabled provider and a username."""

        if not self._enabled:
            return
        if not self._username:
            raise TikTokLiveConfigurationError(
                "TIKTOK_LIVE_USERNAME must be set when TIKTOK_LIVE_ENABLED=true"
            )

        async with self._lifecycle_lock:
            if self._status in {"starting", "connected"}:
                return
            if self._client is not None:
                raise TikTokLiveConfigurationError(
                    "Call stop() before restarting a disconnected or failed provider"
                )
            self._stopping = False
            self._status = "starting"
            self._last_error_code = None

            try:
                bindings = self._bindings or _load_tiktoklive_bindings()
                missing_types = [
                    kind.value for kind in EVENT_TYPES if kind not in bindings.event_types
                ]
                if missing_types:
                    raise TikTokLiveConfigurationError(
                        f"TikTokLive bindings are missing event types: {', '.join(missing_types)}"
                    )
                client = bindings.client_factory(unique_id=self._username)
                self._client = client
                for kind in EVENT_TYPES:
                    client.add_listener(bindings.event_types[kind], self._build_handler(kind))
                connection_task = await client.start(fetch_live_check=True)
                if isinstance(connection_task, asyncio.Task):
                    self._connection_task = connection_task
                    self._monitor_task = asyncio.create_task(
                        self._monitor_connection(connection_task),
                        name="tiktok-live-connection-monitor",
                    )
                # The ConnectEvent handler is responsible for transitioning to connected.
                # Do not claim a connection just because the SDK start method returned.
            except BaseException as exc:
                failed_client = self._client
                if failed_client is not None:
                    try:
                        await asyncio.wait_for(
                            failed_client.disconnect(close_client=True),
                            timeout=min(self._shutdown_timeout_seconds, 2.0),
                        )
                    except BaseException:
                        # Preserve the startup failure; cleanup remains best-effort.
                        pass
                self._status = "failed"
                self._last_error_code = _safe_error_code(exc, prefix="provider_start")
                self._client = None
                self._logger.error(
                    "TikTok LIVE provider failed to start",
                    extra={"provider": "tiktok", "error_code": self._last_error_code},
                )
                raise

    async def stop(self) -> None:
        """Disconnect safely during application shutdown; safe if never started."""

        async with self._lifecycle_lock:
            if self._status in {"disabled", "stopped"} and self._client is None:
                return
            self._stopping = True
            self._status = "stopping"
            client = self._client
            monitor_task = self._monitor_task
            try:
                if client is not None:
                    await asyncio.wait_for(
                        client.disconnect(close_client=True),
                        timeout=self._shutdown_timeout_seconds,
                    )
            except asyncio.CancelledError:
                if not self._stopping:
                    self._status = "failed"
                    self._last_error_code = "provider_connection_cancelled"
                    self._logger.error(
                        "TikTok LIVE connection task was cancelled unexpectedly",
                        extra={
                            "provider": "tiktok",
                            "error_code": self._last_error_code,
                        },
                    )
                raise
            except Exception as exc:
                self._last_error_code = _safe_error_code(exc, prefix="provider_stop")
                self._logger.warning(
                    "TikTok LIVE provider did not shut down cleanly",
                    extra={"provider": "tiktok", "error_code": self._last_error_code},
                )
            finally:
                if monitor_task is not None and monitor_task is not asyncio.current_task():
                    try:
                        await asyncio.wait_for(monitor_task, timeout=1.0)
                    except (TimeoutError, asyncio.CancelledError):
                        monitor_task.cancel()
                    except Exception:
                        # The monitor already logs transport failures; shutdown stays best-effort.
                        pass
                self._client = None
                self._connection_task = None
                self._monitor_task = None
                self._status = "stopped" if self._enabled else "disabled"
                self._stopping = False

    def _build_handler(self, event_type: EventType) -> Callable[[object], Awaitable[None]]:
        async def handler(provider_event: object) -> None:
            await self._handle_provider_event(event_type, provider_event)

        return handler

    async def _handle_provider_event(self, event_type: EventType, provider_event: object) -> None:
        self._provider_events_received += 1
        if event_type is EventType.CONNECT:
            room_id = _safe_scalar(getattr(provider_event, "room_id", None))
            if room_id is not None:
                self._session_id = str(room_id)
            self._status = "connected"
        elif event_type is EventType.DISCONNECT and not self._stopping:
            self._status = "disconnected"

        try:
            event = self._normalizer.normalize(
                event_type, provider_event, session_id=self._session_id
            )
        except Exception:
            self._failed_events += 1
            self._last_error_code = "event_normalization_failed"
            self._logger.warning(
                "Could not normalize a TikTok LIVE event",
                extra={"provider": "tiktok", "event_type": event_type.value},
            )
            return

        if event is None:
            self._ignored_gift_updates += 1
            return

        self._normalized_events += 1
        self._last_event_at = datetime.now(UTC).isoformat()
        try:
            result = await self._ingestion_service.ingest(event)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._failed_events += 1
            self._last_error_code = _safe_error_code(exc, prefix="event_ingestion")
            # Never log raw provider payloads; comments and user metadata may be personal data.
            self._logger.error(
                "TikTok LIVE event reached ingestion but could not be processed",
                extra={
                    "provider": "tiktok",
                    "event_type": event_type.value,
                    "error_code": self._last_error_code,
                },
            )
            return

        if getattr(result, "status", None) == "duplicate":
            self._duplicate_events += 1
        else:
            self._processed_events += 1

    async def _monitor_connection(self, connection_task: asyncio.Task[Any]) -> None:
        try:
            await connection_task
        except asyncio.CancelledError:
            if not self._stopping:
                self._status = "failed"
                self._last_error_code = "provider_connection_cancelled"
                self._logger.error(
                    "TikTok LIVE connection task was cancelled unexpectedly",
                    extra={
                        "provider": "tiktok",
                        "error_code": self._last_error_code,
                    },
                )
            raise
        except Exception as exc:
            if not self._stopping:
                self._status = "failed"
                self._last_error_code = _safe_error_code(exc, prefix="provider_connection")
                self._logger.error(
                    "TikTok LIVE connection ended with an error",
                    extra={"provider": "tiktok", "error_code": self._last_error_code},
                )
        else:
            if not self._stopping and self._status not in {"disabled", "stopped", "failed"}:
                self._status = "disconnected"


def _load_tiktoklive_bindings() -> TikTokLiveBindings:
    """Import the optional SDK only when a real provider connection is explicitly enabled."""

    try:
        from TikTokLive import TikTokLiveClient
        from TikTokLive.events import (
            CommentEvent,
            ConnectEvent,
            DisconnectEvent,
            FollowEvent,
            GiftEvent,
            JoinEvent,
            LikeEvent,
            ShareEvent,
        )
    except ImportError as exc:
        raise TikTokLiveConfigurationError(
            "TikTokLive is optional; install requirements-provider.txt before enabling the provider"
        ) from exc

    return TikTokLiveBindings(
        client_factory=TikTokLiveClient,
        event_types={
            EventType.CONNECT: ConnectEvent,
            EventType.DISCONNECT: DisconnectEvent,
            EventType.COMMENT: CommentEvent,
            EventType.GIFT: GiftEvent,
            EventType.LIKE: LikeEvent,
            EventType.FOLLOW: FollowEvent,
            EventType.SHARE: ShareEvent,
            EventType.JOIN: JoinEvent,
        },
    )


def _viewer_from_provider_event(provider_event: object) -> Viewer | None:
    user = getattr(provider_event, "user", None)
    if user is None:
        return None
    provider_user_id = _optional_text(getattr(user, "id", None))
    if provider_user_id is None:
        provider_user_id = _optional_text(getattr(user, "user_id", None))
    username = _optional_text(getattr(user, "unique_id", None))
    display_name = _optional_text(getattr(user, "nickname", None))
    values = {
        "provider_user_id": provider_user_id,
        "username": username,
        "display_name": display_name,
    }
    values = {key: value for key, value in values.items() if value is not None}
    return Viewer(**values) if values else None


def _provider_event_id(provider_event: object) -> str | None:
    """Use only likely message/event identifiers; never synthesize fake dedupe identities."""

    candidates = [getattr(provider_event, "log_id", None), getattr(provider_event, "msg_id", None)]
    common = getattr(provider_event, "common", None)
    if common is not None:
        candidates.extend([getattr(common, "msg_id", None), getattr(common, "message_id", None)])
    for candidate in candidates:
        value = _optional_text(candidate)
        if value is not None and len(value) <= 256:
            return value
    return None


def _safe_scalar(value: object) -> str | int | float | bool | None:
    if value is None or type(value) in {str, int, float, bool}:
        return value
    if isinstance(value, (str, int, float, bool)):
        return value
    return None


def _optional_text(value: object) -> str | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (str, int, float)):
        result = str(value).strip()
        return result or None
    return None


def _positive_int(value: object, *, default: int) -> int:
    if type(value) is int and value > 0:
        return value
    return default


def _nonnegative_int(value: object) -> int | None:
    if type(value) is int and value >= 0:
        return value
    return None


def _clean_username(username: str | None) -> str | None:
    if username is None:
        return None
    cleaned = username.strip().lstrip("@").strip()
    return cleaned or None


def _safe_error_code(exc: BaseException, *, prefix: str) -> str:
    exception_name = type(exc).__name__.lower()
    # Keep the externally visible code short and stable; the exception message is not exposed.
    safe_name = "".join(char for char in exception_name if char.isalnum() or char == "_")[:48]
    return f"{prefix}_{safe_name or 'unknown'}"
