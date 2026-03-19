"""WebSocket handler for real-time room messaging."""

import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.db.database import async_session
from app.models.message import Message
from app.models.room import Room
from app.services.orchestrator import route_message

logger = logging.getLogger(__name__)

router = APIRouter()


class ConnectionManager:
    def __init__(self):
        self._rooms: dict[str, set[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, room_id: str) -> None:
        await websocket.accept()
        if room_id not in self._rooms:
            self._rooms[room_id] = set()
        self._rooms[room_id].add(websocket)
        logger.info("WS connect room=%s total=%s", room_id, len(self._rooms[room_id]))

    def disconnect(self, websocket: WebSocket, room_id: str) -> None:
        if room_id in self._rooms:
            self._rooms[room_id].discard(websocket)
            if not self._rooms[room_id]:
                del self._rooms[room_id]

    async def broadcast(self, room_id: str, data: dict) -> None:
        if room_id not in self._rooms:
            return
        payload = json.dumps(data)
        dead = set()
        for ws in self._rooms[room_id]:
            try:
                await ws.send_text(payload)
            except Exception:
                dead.add(ws)
        for ws in dead:
            self._rooms[room_id].discard(ws)


manager = ConnectionManager()


async def _room_exists(db, room_id: str) -> bool:
    result = await db.execute(select(Room.id).where(Room.id == room_id))
    return result.scalar_one_or_none() is not None


def message_to_dict(msg: Message) -> dict:
    return {
        "type": "chat",
        "id": msg.id,
        "room_id": msg.room_id,
        "sender_type": msg.sender_type,
        "sender_name": msg.sender_name,
        "content": msg.content,
        "created_at": msg.created_at.isoformat() if msg.created_at else None,
    }


def stream_chunk_to_dict(msg: Message, content: str) -> dict:
    return {
        "type": "stream_chunk",
        "id": msg.id,
        "room_id": msg.room_id,
        "sender_type": msg.sender_type,
        "sender_name": msg.sender_name,
        "content": content,
        "created_at": msg.created_at.isoformat() if msg.created_at else None,
    }


@router.websocket("/ws/{room_id}")
async def websocket_endpoint(websocket: WebSocket, room_id: str):
    async with async_session() as db:
        if not await _room_exists(db, room_id):
            await websocket.accept()
            await websocket.send_text(
                json.dumps({"type": "error", "content": "Room not found"})
            )
            await websocket.close(code=4404)
            return

    await manager.connect(websocket, room_id)

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                continue

            if data.get("type") == "chat":
                sender_name = data.get("sender_name", "User")
                content = data.get("content", "").strip()
                if not content:
                    continue

                async with async_session() as db:
                    if not await _room_exists(db, room_id):
                        await websocket.send_text(
                            json.dumps({"type": "error", "content": "Room not found"})
                        )
                        manager.disconnect(websocket, room_id)
                        await websocket.close(code=4404)
                        return

                    message = Message(
                        room_id=room_id,
                        sender_type="human",
                        sender_name=sender_name,
                        content=content,
                    )
                    db.add(message)
                    try:
                        await db.commit()
                    except IntegrityError:
                        await db.rollback()
                        await websocket.send_text(
                            json.dumps({"type": "error", "content": "Room not found"})
                        )
                        manager.disconnect(websocket, room_id)
                        await websocket.close(code=4404)
                        return
                    await db.refresh(message)
                    await manager.broadcast(room_id, message_to_dict(message))

                    try:
                        async def on_agent_response(resp_msg: Message):
                            await manager.broadcast(room_id, message_to_dict(resp_msg))

                        async def on_agent_status(agent_name: str, status: str):
                            await manager.broadcast(
                                room_id,
                                {
                                    "type": "status",
                                    "agent_name": agent_name,
                                    "status": status,
                                },
                            )

                        async def on_agent_stream(stream_msg: Message, content: str):
                            await manager.broadcast(
                                room_id,
                                stream_chunk_to_dict(stream_msg, content),
                            )

                        await route_message(
                            message,
                            db,
                            on_response=on_agent_response,
                            on_status=on_agent_status,
                            on_stream=on_agent_stream,
                        )
                        await db.commit()
                    except Exception as e:
                        logger.error("Agent routing error: %s", e, exc_info=True)
                        await manager.broadcast(
                            room_id,
                            {
                                "type": "chat",
                                "id": "",
                                "room_id": room_id,
                                "sender_type": "system",
                                "sender_name": "System",
                                "content": f"Agent error: {e}",
                                "created_at": None,
                            },
                        )

            elif data.get("type") == "ping":
                await websocket.send_text(json.dumps({"type": "pong"}))

    except WebSocketDisconnect:
        manager.disconnect(websocket, room_id)
    except Exception as e:
        logger.error("WebSocket error: %s", e, exc_info=True)
        manager.disconnect(websocket, room_id)
