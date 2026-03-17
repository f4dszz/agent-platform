"""WebSocket handler — real-time message broadcasting."""

import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.db.database import async_session
from app.models.message import Message
from app.services.orchestrator import route_message, extract_mentions, get_enabled_agents

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
        logger.info(f"WS connect room={room_id} total={len(self._rooms[room_id])}")

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


@router.websocket("/ws/{room_id}")
async def websocket_endpoint(websocket: WebSocket, room_id: str):
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
                    # Save & broadcast human message
                    message = Message(
                        room_id=room_id,
                        sender_type="human",
                        sender_name=sender_name,
                        content=content,
                    )
                    db.add(message)
                    await db.commit()
                    await db.refresh(message)
                    await manager.broadcast(room_id, message_to_dict(message))

                    # Determine mentioned agents
                    mentions = extract_mentions(content)
                    if not mentions:
                        continue

                    # Resolve which actual agent names are targeted
                    enabled = await get_enabled_agents(db)
                    agent_names = set()
                    if "all" in mentions:
                        agent_names = {a.name for a in enabled}
                    else:
                        enabled_map = {a.name.lower() for a in enabled}
                        agent_names = {m for m in mentions if m in enabled_map}

                    # Broadcast "working" for each real agent
                    for name in agent_names:
                        await manager.broadcast(room_id, {
                            "type": "status",
                            "agent_name": name,
                            "status": "working",
                        })

                    try:
                        # on_response callback: broadcast each agent reply as it arrives
                        async def on_agent_response(resp_msg: Message):
                            await manager.broadcast(room_id, message_to_dict(resp_msg))
                            # Mark this specific agent as idle
                            await manager.broadcast(room_id, {
                                "type": "status",
                                "agent_name": resp_msg.sender_name,
                                "status": "idle",
                            })

                        await route_message(message, db, on_response=on_agent_response)
                        await db.commit()
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
                        # Ensure all agents marked idle
                        for name in agent_names:
                            await manager.broadcast(room_id, {
                                "type": "status",
                                "agent_name": name,
                                "status": "idle",
                            })

            elif data.get("type") == "ping":
                await websocket.send_text(json.dumps({"type": "pong"}))

    except WebSocketDisconnect:
        manager.disconnect(websocket, room_id)
    except Exception as e:
        logger.error(f"WebSocket error: {e}", exc_info=True)
        manager.disconnect(websocket, room_id)
