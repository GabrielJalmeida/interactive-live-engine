"""Development/test-only controls for the provider diagnostics Experience."""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from backend.app.experiences.provider_diagnostics import (
    ProviderDiagnosticsExperience,
    register_provider_diagnostics,
)

router = APIRouter(prefix="/api/v1/dev/provider-diagnostics", tags=["development"])
_DIAGNOSTICS_SLUG = ProviderDiagnosticsExperience.slug


def _conflict(code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=409,
        content={"error": {"code": code, "message": message}},
    )


@router.post(
    "/start", response_model=None, summary="Start the development provider diagnostics Experience"
)
async def start_provider_diagnostics(request: Request) -> dict[str, str] | JSONResponse:
    """Start diagnostics explicitly; never activates automatically in the normal dev setup."""

    runtime = request.app.state.engine_runtime
    active_slug = runtime.manager.active_slug
    if active_slug == _DIAGNOSTICS_SLUG:
        return {"status": "already_running", "experience": _DIAGNOSTICS_SLUG}
    if active_slug is not None:
        return _conflict(
            "EXPERIENCE_ALREADY_ACTIVE",
            "Stop the active Experience before starting provider diagnostics.",
        )
    register_provider_diagnostics(runtime)
    await runtime.start_experience(_DIAGNOSTICS_SLUG)
    return {"status": "running", "experience": _DIAGNOSTICS_SLUG}


@router.post(
    "/stop", response_model=None, summary="Stop the development provider diagnostics Experience"
)
async def stop_provider_diagnostics(request: Request) -> dict[str, str] | JSONResponse:
    """Stop diagnostics without affecting a different active Experience."""

    runtime = request.app.state.engine_runtime
    active_slug = runtime.manager.active_slug
    if active_slug is None:
        return {"status": "stopped", "experience": _DIAGNOSTICS_SLUG}
    if active_slug != _DIAGNOSTICS_SLUG:
        return _conflict(
            "DIFFERENT_EXPERIENCE_ACTIVE",
            "The active Experience is not provider diagnostics; it was left untouched.",
        )
    await runtime.stop_experience()
    return {"status": "stopped", "experience": _DIAGNOSTICS_SLUG}
