"""FastAPI application factory and explicit composition root."""

from fastapi import FastAPI

from backend.app.api.engine_state import router as engine_state_router
from backend.app.api.experiences import router as experiences_router
from backend.app.api.health import router as health_router
from backend.app.config import Settings
from backend.app.runtime.engine_runtime import EngineRuntime


def create_app(
    settings: Settings | None = None,
    runtime: EngineRuntime | None = None,
) -> FastAPI:
    """Create an app with injected settings/runtime; no concrete Experience is registered."""

    resolved_settings = settings or Settings()
    resolved_runtime = runtime or EngineRuntime()
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
    application.include_router(health_router)
    application.include_router(engine_state_router)
    application.include_router(experiences_router)
    return application


app = create_app()
