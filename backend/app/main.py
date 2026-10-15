"""FastAPI application factory and explicit composition root."""

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
    EventProcessingError,
    EventPublicationError,
    InMemoryEventDeduplicationStore,
)
from backend.app.config import Settings
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
    """Create the app and connect concrete infrastructure only at the composition root."""

    resolved_settings = settings or Settings()
    resolved_realtime = realtime_manager
    resolved_runtime = runtime

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

    application = FastAPI(
        title="Interactive Live Engine",
        version="0.1.0",
        description=(
            "Reusable infrastructure for event-driven interactive live experiences. "
            "The Runtime is generic and no gameplay Experience is bundled."
        ),
    )
    application.state.settings = resolved_settings
    application.state.engine_runtime = resolved_runtime
    application.state.realtime_manager = resolved_realtime

    @application.exception_handler(RequestValidationError)
    async def request_validation_error_handler(_request: Request, _exc: RequestValidationError):
        return _error_response(
            422,
            "INVALID_REQUEST",
            "The request does not match the expected schema or validation rules.",
        )

    @application.exception_handler(NoActiveExperienceError)
    async def no_active_experience_handler(_request: Request, _exc: NoActiveExperienceError):
        return _error_response(
            409,
            "NO_ACTIVE_EXPERIENCE",
            "An Experience must be active before events can be processed.",
        )

    @application.exception_handler(EventProcessingError)
    async def event_processing_error_handler(_request: Request, _exc: EventProcessingError):
        return _error_response(
            500,
            "EVENT_PROCESSING_FAILED",
            "The event could not be processed.",
        )

    @application.exception_handler(EventPublicationError)
    async def event_publication_error_handler(_request: Request, _exc: EventPublicationError):
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

    if resolved_settings.app_env in {"development", "test"}:
        from backend.app.api.dev_events import router as dev_events_router

        deduplication_store = (
            event_deduplication_store
            if event_deduplication_store is not None
            else InMemoryEventDeduplicationStore()
        )
        application.state.event_ingestion_service = EventIngestionService(
            resolved_runtime,
            deduplication_store,
        )
        application.include_router(dev_events_router)

    return application


app = create_app()
