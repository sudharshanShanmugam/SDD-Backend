"""
WebSocket event handlers and routes.
Handles authentication, room subscriptions, presence, collaboration, and all event types.
"""
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query, status

from app.websockets.events import EventType
from app.websockets.manager import websocket_manager

logger = logging.getLogger(__name__)

router = APIRouter()


async def authenticate_websocket(token: str) -> Optional[dict]:
    """
    Validate JWT token for WebSocket connection.
    Returns decoded payload dict or None if invalid.
    """
    try:
        from app.services.auth_service import AuthService
        auth_svc = AuthService(db=None)  # type: ignore
        payload = auth_svc.verify_token(token)
        return payload
    except Exception as exc:
        logger.debug("WebSocket auth failed: %s", exc)
        return None


@router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    token: str = Query(..., description="JWT access token"),
    project_id: Optional[str] = Query(None, description="Join project room on connect"),
    org_id: Optional[str] = Query(None, description="Join org room on connect"),
):
    """
    Primary WebSocket endpoint for the SDD platform.

    Authentication: Pass JWT as ?token= query parameter.
    Rooms auto-subscribed: user personal room, project room (if project_id provided).

    Client → Server message format:
    {
        "event": "<event_type>",
        "data": { ... },
        "request_id": "<optional_correlation_id>"
    }

    Supported client events:
    - connection.ping            → connection.pong
    - subscribe                  → subscribe to a room_id
    - unsubscribe                → unsubscribe from a room_id
    - collaboration.cursor       → broadcast cursor position
    - collaboration.edit         → broadcast field edit (CRDT-style)
    - collaboration.lock         → lock entity for editing
    - collaboration.unlock       → unlock entity
    - presence.update            → update presence status
    """
    # ── Authentication ─────────────────────────────────────────────────────
    payload = await authenticate_websocket(token)
    if not payload:
        await websocket.close(code=4001, reason="Unauthorized: Invalid token")
        return

    user_id: str = payload.get("sub", "")
    user_email: str = payload.get("email", "")
    user_name: str = payload.get("full_name", user_email.split("@")[0] if user_email else "Unknown")

    if not user_id:
        await websocket.close(code=4001, reason="Unauthorized: Missing user ID")
        return

    connection_id = str(uuid.uuid4())

    try:
        # ── Connect ────────────────────────────────────────────────────────
        await websocket_manager.connect(
            websocket=websocket,
            user_id=user_id,
            user_name=user_name,
            connection_id=connection_id,
        )

        # Auto-join project room
        if project_id:
            await websocket_manager.subscribe(
                connection_id=connection_id,
                room_id=f"project:{project_id}",
            )

        # Auto-join org room
        if org_id:
            await websocket_manager.subscribe(
                connection_id=connection_id,
                room_id=f"org:{org_id}",
            )

        # ── Message loop ───────────────────────────────────────────────────
        while True:
            raw = await websocket.receive_text()

            try:
                message = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_text(json.dumps({
                    "event": EventType.CONNECTION_ERROR,
                    "data": {"error": "Invalid JSON"},
                }))
                continue

            event = message.get("event", "")
            data = message.get("data", {})
            request_id = message.get("request_id")

            await _handle_client_message(
                connection_id=connection_id,
                user_id=user_id,
                user_name=user_name,
                project_id=project_id,
                websocket=websocket,
                event=event,
                data=data,
                request_id=request_id,
            )

    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected: user=%s conn=%s", user_id, connection_id)
    except Exception as exc:
        logger.error("WebSocket error: user=%s conn=%s error=%s", user_id, connection_id, exc)
    finally:
        await websocket_manager.disconnect(connection_id)


async def _handle_client_message(
    connection_id: str,
    user_id: str,
    user_name: str,
    project_id: Optional[str],
    websocket: WebSocket,
    event: str,
    data: dict,
    request_id: Optional[str],
) -> None:
    """Route incoming client messages to the appropriate handler."""

    def _response(evt: str, payload: dict) -> str:
        msg = {
            "event": evt,
            "data": payload,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        if request_id:
            msg["request_id"] = request_id
        return json.dumps(msg, default=str)

    # ── Ping / Pong ────────────────────────────────────────────────────────
    if event in (EventType.CONNECTION_PING, "ping"):
        await websocket.send_text(_response(EventType.CONNECTION_PONG, {
            "pong": datetime.now(timezone.utc).isoformat(),
        }))

    # ── Room subscribe ─────────────────────────────────────────────────────
    elif event == EventType.SUBSCRIBE:
        room_id = data.get("room_id")
        if room_id:
            await websocket_manager.subscribe(connection_id=connection_id, room_id=room_id)
            await websocket.send_text(_response("subscribed", {"room_id": room_id}))
            # Send current presence for project rooms
            if room_id.startswith("project:"):
                presence = await websocket_manager.get_room_presence(room_id)
                await websocket.send_text(_response(EventType.PRESENCE_LIST, {
                    "room_id": room_id,
                    "users": presence,
                }))

    # ── Room unsubscribe ───────────────────────────────────────────────────
    elif event == EventType.UNSUBSCRIBE:
        room_id = data.get("room_id")
        if room_id:
            await websocket_manager.unsubscribe(connection_id=connection_id, room_id=room_id)
            await websocket.send_text(_response("unsubscribed", {"room_id": room_id}))

    # ── Collaboration: cursor movement ─────────────────────────────────────
    elif event == EventType.COLLABORATION_CURSOR:
        entity_id = data.get("entity_id", "")
        entity_type = data.get("entity_type", "")
        position = data.get("position", {})
        if entity_id:
            await websocket_manager.broadcast_to_entity(
                entity_type=entity_type,
                entity_id=entity_id,
                event=EventType.COLLABORATION_CURSOR,
                data={
                    "user_id": user_id,
                    "user_name": user_name,
                    "entity_id": entity_id,
                    "position": position,
                },
                exclude_user_id=user_id,
            )

    # ── Collaboration: field edit ──────────────────────────────────────────
    elif event == EventType.COLLABORATION_EDIT:
        entity_id = data.get("entity_id", "")
        entity_type = data.get("entity_type", "")
        field = data.get("field", "")
        value = data.get("value")
        version = data.get("version", 0)
        if entity_id and field:
            await websocket_manager.broadcast_to_entity(
                entity_type=entity_type,
                entity_id=entity_id,
                event=EventType.COLLABORATION_EDIT,
                data={
                    "user_id": user_id,
                    "entity_id": entity_id,
                    "field": field,
                    "value": value,
                    "version": version,
                },
                exclude_user_id=user_id,
            )

    # ── Collaboration: entity lock ─────────────────────────────────────────
    elif event == EventType.COLLABORATION_LOCK:
        entity_id = data.get("entity_id", "")
        entity_type = data.get("entity_type", "")
        if entity_id:
            room_id = f"entity:{entity_type}:{entity_id}"
            await websocket_manager.subscribe(connection_id=connection_id, room_id=room_id)
            await websocket_manager.broadcast_to_entity(
                entity_type=entity_type,
                entity_id=entity_id,
                event=EventType.COLLABORATION_LOCK,
                data={"user_id": user_id, "user_name": user_name, "entity_id": entity_id},
            )

    # ── Collaboration: entity unlock ───────────────────────────────────────
    elif event == EventType.COLLABORATION_UNLOCK:
        entity_id = data.get("entity_id", "")
        entity_type = data.get("entity_type", "")
        if entity_id:
            await websocket_manager.broadcast_to_entity(
                entity_type=entity_type,
                entity_id=entity_id,
                event=EventType.COLLABORATION_UNLOCK,
                data={"user_id": user_id, "entity_id": entity_id},
            )

    # ── Presence: update ──────────────────────────────────────────────────
    elif event == EventType.PRESENCE_UPDATE:
        status_val = data.get("status", "active")
        current_page = data.get("current_page")
        if project_id:
            await websocket_manager.broadcast_to_project(
                project_id=project_id,
                event=EventType.PRESENCE_UPDATE,
                data={
                    "user_id": user_id,
                    "status": status_val,
                    "current_page": current_page,
                },
            )

    # ── Presence: list ────────────────────────────────────────────────────
    elif event == EventType.PRESENCE_LIST:
        room_id = data.get("room_id", f"project:{project_id}" if project_id else "")
        if room_id:
            users = await websocket_manager.get_room_presence(room_id)
            await websocket.send_text(_response(EventType.PRESENCE_LIST, {
                "room_id": room_id,
                "users": users,
            }))

    # ── Unknown event ──────────────────────────────────────────────────────
    else:
        logger.debug("Unknown WS event from user=%s: %s", user_id, event)


@router.websocket("/ws/presence/{org_id}")
async def presence_websocket(
    websocket: WebSocket,
    org_id: str,
    token: str = Query(...),
):
    """
    Dedicated presence channel for organization-wide user presence.
    Sends periodic presence updates for all online org members.
    """
    payload = await authenticate_websocket(token)
    if not payload:
        await websocket.close(code=4001, reason="Unauthorized")
        return

    user_id = payload.get("sub", "")
    connection_id = str(uuid.uuid4())

    await websocket_manager.connect(
        websocket=websocket,
        user_id=user_id,
        user_name=payload.get("email", ""),
        connection_id=connection_id,
    )
    await websocket_manager.subscribe(connection_id=connection_id, room_id=f"org:{org_id}")

    try:
        while True:
            raw = await websocket.receive_text()
            msg = json.loads(raw)
            if msg.get("event") == "ping":
                await websocket.send_text(json.dumps({"event": "pong", "data": {}}))
    except WebSocketDisconnect:
        pass
    finally:
        await websocket_manager.disconnect(connection_id)
