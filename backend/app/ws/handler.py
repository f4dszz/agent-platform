"""WebSocket handler — real-time message broadcasting.

Manages WebSocket connections per room and integrates with the orchestrator
to route messages and broadcast responses.
"""

import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.db.database import async_session
from app.models.message import Message
from app.services.orchestrator import route_message

logger = logging.getLogger(__name__)

router = APIRouter()


class ConnectionManager:
    """Manages WebSocket connections grouped by room."""

    def __init__(self):
        # room_id → set of connected WebSockets
        self._rooms: dict[str, set[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, room_id: str) -> None:
        """Accept a WebSocket connection and add it to a room."""
        await websocket.accept()
        if room_id not in self._rooms:
            self._rooms[room_id] = set()
        self._rooms[room_id].add(websocket)
        logger.info(
            f"Client connected to room {room_id} "
            f"(total: {len(self._rooms[room_id])})"
        )

    def disconnect(self, websocket: WebSocket, room_id: str) -> None:
        """Remove a WebSocket from a room."""
        if room_id in self._rooms:
            self._rooms[room_id].discard(websocket)
            if not self._rooms[room_id]:
                del self._rooms[room_id]
            logger.info(f"Client disconnected from room {room_id}")

    async def broadcast(self, room_id: str, data: dict) -> None:
        """Send a JSON message to all clients in a room."""
        if room_id not in self._rooms:
            return

        payload = json.dumps(data)
        dead_connections = set()

        for ws in self._rooms[room_id]:
            try:
                await ws.send_text(payload)
            except Exception:
                dead_connections.add(ws)

        # Clean up dead connections
        for ws in dead_connections:
            self._rooms[room_id].discard(ws)

    async def send_to(self, websocket: WebSocket, data: dict) -> None:
        """Send a JSON message to a specific client."""
        try:
            await websocket.send_text(json.dumps(data))
        except Exception:
            logger.warning("Failed to send message to client")

    def get_room_count(self, room_id: str) -> int:
        """Get the number of connected clients in a room."""
        return len(self._rooms.get(room_id, set()))


# Singleton connection manager
manager = ConnectionManager()


def message_to_dict(msg: Message) -> dict:
    """Convert a Message ORM object to a dict for WebSocket broadcast."""
    return {
        "type": "chat",
        "id": msg.id,
        "room_id": msg.room_id,
        "sender_type": msg.sender_type,
        "sender_name": msg.sender_name,
        "content": msg.content,
        "created_at": msg.created_at.isoformat() if msg.created_at else None,
    }


@router.websocket("/ws/{room_id}")
async def websocket_endpoint(websocket: WebSocket, room_id: str):
    """WebSocket endpoint for real-time chat in a room.

    Protocol:
      Client sends: {"type": "chat", "sender_name": "User", "content": "Hello @claude"}
      Server broadcasts: {"type": "chat", "id": "...", "sender_type": "human", ...}
      Server broadcasts: {"type": "status", "agent_name": "claude", "status": "working"}
      Server broadcasts: {"type": "chat", "id": "...", "sender_type": "claude", ...}
      Server broadcasts: {"type": "status", "agent_name": "claude", "status": "idle"}
    """
    await manager.connect(websocket, room_id)

    try:
        while True:
            # Receive message from client
            raw = await websocket.receive_text()
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                await manager.send_to(websocket, {
                    "type": "error",
                    "content": "Invalid JSON",
                })
                continue

            msg_type = data.get("type", "chat")

            if msg_type == "chat":
                sender_name = data.get("sender_name", "User")
                content = data.get("content", "").strip()

                if not content:
                    continue

                # Save human message to DB
                async with async_session() as db:
                    message = Message(
                        room_id=room_id,
                        sender_type="human",
                        sender_name=sender_name,
                        content=content,
                    )
                    db.add(message)
                    await db.commit()
                    await db.refresh(message)

                    # Broadcast human message to all clients
                    await manager.broadcast(room_id, message_to_dict(message))

                    # Route to agents via orchestrator
                    from app.services.orchestrator import extract_mentions

                    mentions = extract_mentions(content)
                    if mentions:
                        for mention in mentions:
                            await manager.broadcast(room_id, {
                                "type": "status",
                                "agent_name": mention,
                                "status": "working",
                            })

                        try:
                            # Get agent responses
                            agent_responses = await route_message(message, db)
                            await db.commit()

                            # Broadcast each agent response
                            for resp in agent_responses:
                                await manager.broadcast(room_id, message_to_dict(resp))
                        except Exception as e:
                            logger.error(f"Agent routing error: {e}", exc_info=True)
                            await manager.broadcast(room_id, {
                                "type": "chat",
                                "id": "",
                                "room_id": room_id,
                                "sender_type": "system",
                                "sender_name": "System",
                                "content": f"Agent error: {e}",
                                "created_at": None,
                            })
                        finally:
                            # Always broadcast "idle" status
                            for mention in mentions:
                                await manager.broadcast(room_id, {
                                    "type": "status",
                                    "agent_name": mention,
                                    "status": "idle",
                                })

            elif msg_type == "ping":
                await manager.send_to(websocket, {"type": "pong"})

    except WebSocketDisconnect:
        manager.disconnect(websocket, room_id)
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        manager.disconnect(websocket, room_id)
