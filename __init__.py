"""Server-to-client WebSocket endpoint for versioned output envelopes."""

from urllib.parse import urlsplit

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter(tags=["realtime"])


def _origin_matches_request_host(websocket: WebSocket) -> bool:
    """Require browser connections to be same-origin; allow origin-less native clients."""

    origin = websocket.headers.get("origin")
    if origin is None:
        return True

    parsed = urlsplit(origin)
    request_scheme = "https" if websocket.scope.get("scheme") == "wss" else "http"
    request_host = websocket.headers.get("host", "").casefold()
    return (
        parsed.scheme == request_scheme
        and parsed.netloc.casefold() == request_host
        and parsed.username is None
        and parsed.password is None
    )


@router.websocket("/ws/events")
async def websocket_events(websocket: WebSocket) -> None:
    """Deliver Engine outputs only; client-originated application messages are forbidden."""

    if not _origin_matches_request_host(websocket):
        # Before accept, Starlette denies the handshake rather than opening a socket.
        await websocket.close(code=1008, reason="WebSocket must be same-origin")
        return

    realtime_manager = websocket.app.state.realtime_manager
    connected = False
    try:
        connected = await realtime_manager.connect(websocket)
        if not connected:
            return

        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                return
            if message.get("text") is not None or message.get("bytes") is not None:
                await websocket.close(
                    code=1008,
                    reason="This WebSocket is a server-to-client channel",
                )
                return
    except WebSocketDisconnect:
        return
    finally:
        if connected:
            await realtime_manager.disconnect(websocket)
