"""Read-only endpoints for registered Experiences."""

from fastapi import APIRouter, Request

from backend.app.runtime.experience_loader import ExperienceMetadata

router = APIRouter(prefix="/api/v1", tags=["experiences"])


@router.get(
    "/experiences",
    response_model=list[ExperienceMetadata],
    summary="List registered Experiences",
)
def list_experiences(request: Request) -> list[ExperienceMetadata]:
    """List factories registered in this process; this is not a public game catalogue."""

    return request.app.state.engine_runtime.list_experiences()
