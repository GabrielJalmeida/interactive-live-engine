"""FastAPI application factory and explicit infrastructure composition root."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from backend.app.api.engine_state import router as engine_state_router
from backend.app.api.experiences import router as experiences_router
from backend.app.api.health import router as health_router
from backend.app.api.realtime_harness import router as realtime_harness_router
from backend.app.api.websocket import router as websocket_router
from backend.app.application.event_ingestion import (
    EventDeduplicationPort,
    EventIngestionService,
    EventPersistenceError,
    EventProcessingError,
    EventPublicationError,
    InMemoryEventDeduplicationStore,
)
from backend.app.config import Settings
from backend.app.persistence.database import create_database_engine, create_session_factory
from backend.app.persistence.event_repository import SqlAlchemyEventStore
from backend.app.realtime.realtime_manager import RealtimeManager
from backend.app.runtime.engine_runtime import EngineRuntime
from backend.app.runtime.experience_manager import NoActiveExperienceError


def _error_response(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message}},
    )


def create_app(
    settings: Settings | None = None,
    runtime: EngineRuntime | None = None,
    realtime_manager: RealtimeManager | None = None,
    event_deduplication_store: EventDeduplicationPort | None = None,
) -> FastAPI:
    """Create the application and wire concrete persistence/realtime adapters explicitly."""

    resolved_settings = settings or Settings()
    resolved_realtime = realtime_manager
    resolved_runtime = runtime
    owned_database_engine = None

    if resolved_runtime is None:
        resolved_realtime = resolved_realtime or RealtimeManager(
            send_timeout_seconds=resolved_settings.websocket_send_timeout_seconds
        )
        resolved_runtime = EngineRuntime(output_publisher=resolved_realtime)
    else:
        existing_publisher = resolved_runtime.output_publisher
        if resolved_realtime is None and isinstance(existing_publisher, RealtimeManager):
            resolved_realtime = existing_publisher
        if resolved_realtime is None:
            resolved_realtime = RealtimeManager(
                send_timeout_seconds=resolved_settings.websocket_send_timeout_seconds
            )
        if existing_publisher is None:
            resolved_runtime.bind_output_publisher(resolved_realtime)
        elif existing_publisher is not resolved_realtime:
            raise ValueError(
                "The supplied Runtime and application must share the same output publisher"
            )

    if event_deduplication_store is not None:
        deduplication_store = event_deduplication_store
    elif resolved_settings.app_env == "test":
        deduplication_store = InMemoryEventDeduplicationStore()
    else:
        owned_database_engine = create_database_engine(resolved_settings.database_url)
        deduplication_store = SqlAlchemyEventStore(create_session_factory(owned_database_engine))

    @asynccontextmanager
    async def lifespan(_application: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            if owned_database_engine is not None:
                owned_database_engine.dispose()

    application = FastAPI(
        title="Interactive Live Engine",
        version="0.1.0",
        description=(
            "Reusable infrastructure for event-driven interactive live experiences. "
            "The Runtime is generic and no gameplay Experience is bundled."
        ),
        lifespan=lifespan,
    )
    application.state.settings = resolved_settings
    application.state.database_engine = owned_database_engine
    application.state.engine_runtime = resolved_runtime
    application.state.realtime_manager = resolved_realtime
    application.state.event_deduplication_store = deduplication_store

    @application.exception_handler(RequestValidationError)
    async def request_validation_error_handler(
        _request: Request, _exc: RequestValidationError
    ) -> JSONResponse:
        return _error_response(
            422,
            "INVALID_REQUEST",
            "The request does not match the expected schema or validation rules.",
        )

    @application.exception_handler(NoActiveExperienceError)
    async def no_active_experience_handler(
        _request: Request, _exc: NoActiveExperienceError
    ) -> JSONResponse:
        return _error_response(
            409,
            "NO_ACTIVE_EXPERIENCE",
            "An Experience must be active before events can be processed.",
        )

    @application.exception_handler(EventProcessingError)
    async def event_processing_error_handler(
        _request: Request, _exc: EventProcessingError
    ) -> JSONResponse:
        return _error_response(
            500,
            "EVENT_PROCESSING_FAILED",
            "The event could not be processed.",
        )

    @application.exception_handler(EventPersistenceError)
    async def event_persistence_error_handler(
        _request: Request, _exc: EventPersistenceError
    ) -> JSONResponse:
        return _error_response(
            500,
            "EVENT_PERSISTENCE_FAILED",
            "The event could not be persisted safely; verify its status before retrying.",
        )

    @application.exception_handler(EventPublicationError)
    async def event_publication_error_handler(
        _request: Request, _exc: EventPublicationError
    ) -> JSONResponse:
        return _error_response(
            500,
            "OUTPUT_PUBLICATION_FAILED",
            "The event was processed, but its outputs could not be published.",
        )

    application.include_router(health_router)
    application.include_router(engine_state_router)
    application.include_router(experiences_router)
    application.include_router(websocket_router)
    application.include_router(realtime_harness_router)

    # The provider adapter in the LIVE environment must use the same ingestion service;
    # only the HTTP simulation route is restricted to development/test.
    application.state.event_ingestion_service = EventIngestionService(
        resolved_runtime,
        deduplication_store,
    )
    if resolved_settings.app_env in {"development", "test"}:
        from backend.app.api.dev_events import router as dev_events_router

        application.include_router(dev_events_router)

    return application


app = create_app()
