"""FastAPI application factory and explicit composition root."""

from backend.app.api.engine_state import router as engine_state_router
from backend.app.api.experiences import router as experiences_router
from backend.app.api.health import router as health_router
from fastapi import FastAPI

from backend.app.api.realtime_harness import router as realtime_harness_router
from backend.app.api.websocket import router as websocket_router
from backend.app.config import Settings
from backend.app.realtime.realtime_manager import RealtimeManager
from backend.app.runtime.engine_runtime import EngineRuntime


def create_app(
    settings: Settings | None = None,
    runtime: EngineRuntime | None = None,
    realtime_manager: RealtimeManager | None = None,
) -> FastAPI:
    """Create the application and explicitly connect Runtime to its output transport."""

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
    application.include_router(health_router)
    application.include_router(engine_state_router)
    application.include_router(experiences_router)
    application.include_router(websocket_router)
    application.include_router(realtime_harness_router)
    return application


app = create_app()
