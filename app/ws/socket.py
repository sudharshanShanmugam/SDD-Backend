"""
Socket.IO server — real-time collaboration and live-update events.

The server is created here as a module-level singleton so it can be
imported by both main.py (to mount the ASGI app) and any API routes
that need to emit events (e.g. after a story is generated).

Usage from a route:
    from app.ws.socket import sio
    await sio.emit('story:created', data, room=f'project:{project_id}')
"""
import logging

import socketio

from app.core.config import settings

logger = logging.getLogger(__name__)

# ── Socket.IO async server ────────────────────────────────────────────────────

sio = socketio.AsyncServer(
    async_mode="asgi",
    cors_allowed_origins=settings.ALLOWED_ORIGINS or "*",
    logger=False,          # Use our own logging
    engineio_logger=False,
)


# ── Connection lifecycle ──────────────────────────────────────────────────────

@sio.event
async def connect(sid: str, environ: dict, auth: dict | None = None) -> None:
    logger.debug("[Socket.IO] Client connected: %s", sid)


@sio.event
async def disconnect(sid: str) -> None:
    logger.debug("[Socket.IO] Client disconnected: %s", sid)


# ── Room management ───────────────────────────────────────────────────────────

@sio.on("join:room")
async def on_join_room(sid: str, data: dict) -> None:
    """Join a named room (e.g. project:{project_id})."""
    room = data.get("room") if isinstance(data, dict) else str(data)
    if room:
        await sio.enter_room(sid, room)
        logger.debug("[Socket.IO] %s joined room %s", sid, room)


@sio.on("leave:room")
async def on_leave_room(sid: str, data: dict) -> None:
    """Leave a named room."""
    room = data.get("room") if isinstance(data, dict) else str(data)
    if room:
        await sio.leave_room(sid, room)
        logger.debug("[Socket.IO] %s left room %s", sid, room)


# ── Ping / keep-alive ─────────────────────────────────────────────────────────

@sio.on("ping")
async def on_ping(sid: str, _data: object = None) -> str:
    return "pong"
