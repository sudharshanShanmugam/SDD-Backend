"""
WebSocket Connection Manager
Room-based subscriptions, presence tracking, Redis-backed state
"""
import asyncio
import json
from typing import Dict, Set, Optional
from datetime import datetime, timezone

import redis.asyncio as aioredis
import structlog
from fastapi import WebSocket
from pydantic import BaseModel

from app.core.config import settings

logger = structlog.get_logger(__name__)


class ConnectionInfo(BaseModel):
    user_id: str
    organization_id: str
    project_id: Optional[str] = None
    connected_at: str
    last_ping: str


class WebSocketManager:
    """
    Manages WebSocket connections with:
    - Per-user connections (multiple devices)
    - Project room subscriptions
    - Organization-wide broadcasts
    - Redis-backed presence tracking
    - Graceful disconnect handling
    """

    def __init__(self):
        # user_id -> set of WebSocket connections
        self._user_connections: Dict[str, Set[WebSocket]] = {}
        # project_id -> set of user_ids
        self._project_rooms: Dict[str, Set[str]] = {}
        # org_id -> set of user_ids
        self._org_rooms: Dict[str, Set[str]] = {}
        # websocket -> ConnectionInfo
        self._connection_info: Dict[WebSocket, ConnectionInfo] = {}
        self._redis: Optional[aioredis.Redis] = None
        self._lock = asyncio.Lock()

    async def startup(self):
        self._redis = aioredis.from_url(
            str(settings.REDIS_URL),
            encoding="utf-8",
            decode_responses=True,
        )
        logger.info("WebSocketManager started")

    async def shutdown(self):
        if self._redis:
            await self._redis.aclose()
        logger.info("WebSocketManager shut down")

    async def connect(
        self,
        websocket: WebSocket,
        user_id: str,
        organization_id: str,
        project_id: Optional[str] = None,
    ) -> None:
        await websocket.accept()
        async with self._lock:
            # Track connection
            if user_id not in self._user_connections:
                self._user_connections[user_id] = set()
            self._user_connections[user_id].add(websocket)

            # Room membership
            if organization_id not in self._org_rooms:
                self._org_rooms[organization_id] = set()
            self._org_rooms[organization_id].add(user_id)

            if project_id:
                if project_id not in self._project_rooms:
                    self._project_rooms[project_id] = set()
                self._project_rooms[project_id].add(user_id)

            now = datetime.now(timezone.utc).isoformat()
            self._connection_info[websocket] = ConnectionInfo(
                user_id=user_id,
                organization_id=organization_id,
                project_id=project_id,
                connected_at=now,
                last_ping=now,
            )

        # Track presence in Redis
        if self._redis:
            await self._redis.hset(
                f"presence:{organization_id}",
                user_id,
                json.dumps({"project_id": project_id, "connected_at": now}),
            )
            await self._redis.expire(f"presence:{organization_id}", 86400)  # 24h

        logger.info("websocket_connected", user_id=user_id, project_id=project_id)

        # Broadcast join event to project room
        if project_id:
            await self.broadcast_to_project(
                project_id=project_id,
                event="presence.join",
                data={"user_id": user_id, "project_id": project_id},
                exclude_user=None,
            )

    async def disconnect(self, websocket: WebSocket) -> None:
        info = self._connection_info.get(websocket)
        if not info:
            return

        async with self._lock:
            # Remove from user connections
            if info.user_id in self._user_connections:
                self._user_connections[info.user_id].discard(websocket)
                if not self._user_connections[info.user_id]:
                    del self._user_connections[info.user_id]
                    # User fully disconnected - remove from rooms
                    if info.organization_id in self._org_rooms:
                        self._org_rooms[info.organization_id].discard(info.user_id)
                    if info.project_id and info.project_id in self._project_rooms:
                        self._project_rooms[info.project_id].discard(info.user_id)

            del self._connection_info[websocket]

        # Remove from Redis presence
        if self._redis and info.user_id not in self._user_connections:
            await self._redis.hdel(f"presence:{info.organization_id}", info.user_id)

        logger.info("websocket_disconnected", user_id=info.user_id)

        # Broadcast leave event
        if info.project_id:
            await self.broadcast_to_project(
                project_id=info.project_id,
                event="presence.leave",
                data={"user_id": info.user_id},
            )

    async def send_to_user(self, user_id: str, event: str, data: dict) -> int:
        """Send event to all connections of a specific user. Returns sent count."""
        connections = self._user_connections.get(user_id, set()).copy()
        sent = 0
        message = json.dumps({
            "event": event,
            "data": data,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        for ws in connections:
            try:
                await ws.send_text(message)
                sent += 1
            except Exception:
                await self.disconnect(ws)
        return sent

    async def broadcast_to_project(
        self,
        project_id: str,
        event: str,
        data: dict,
        exclude_user: Optional[str] = None,
    ) -> int:
        """Broadcast event to all users in a project room."""
        user_ids = self._project_rooms.get(project_id, set()).copy()
        sent = 0
        for user_id in user_ids:
            if user_id != exclude_user:
                sent += await self.send_to_user(user_id, event, data)
        return sent

    async def broadcast_to_org(self, org_id: str, event: str, data: dict) -> int:
        """Broadcast event to all users in an organization."""
        user_ids = self._org_rooms.get(org_id, set()).copy()
        sent = 0
        for user_id in user_ids:
            sent += await self.send_to_user(user_id, event, data)
        return sent

    def get_project_presence(self, project_id: str) -> list[str]:
        """Get list of online user IDs in a project."""
        return list(self._project_rooms.get(project_id, set()))

    def is_user_online(self, user_id: str) -> bool:
        return user_id in self._user_connections and bool(self._user_connections[user_id])

    def get_connection_count(self) -> int:
        return sum(len(conns) for conns in self._user_connections.values())


# Module-level singleton — also exported as ws_manager for backward compat
websocket_manager = WebSocketManager()
ws_manager = websocket_manager
