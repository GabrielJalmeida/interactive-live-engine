"""Development-only browser harness for inspecting realtime protocol messages."""

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

router = APIRouter(tags=["development"], include_in_schema=False)
_HARNESS_FILE = Path(__file__).resolve().parents[3] / "clients" / "web" / "base" / "index.html"


@router.get("/dev/realtime-harness")
async def get_realtime_harness(request: Request) -> FileResponse:
    """Serve the manual WebSocket inspection page outside production."""

    if request.app.state.settings.app_env == "production":
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(_HARNESS_FILE, media_type="text/html; charset=utf-8")
