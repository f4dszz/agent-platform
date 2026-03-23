"""WebSocket handler for real-time room messaging."""

import asyncio
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.db.database import async_session
from app.models.agent_artifact import AgentArtifact
from app.models.agent_event import AgentEvent
from app.models.approval_request import ApprovalRequest
from app.models.collaboration_run import CollaborationRun
from app.models.message import Message
from app.models.room import Room
from app.models.run_step import RunStep
from app.services.orchestrator import route_message

logger = logging.getLogger(__name__)

router = APIRouter()
ROOM_LIFECYCLE_CHANNEL = "__rooms__"


class ConnectionManager:
    def __init__(self):
        self._rooms: dict[str, set[WebSocket]] = {}
        self._send_locks: dict[WebSocket, asyncio.Lock] = {}

    async def connect(self, websocket: WebSocket, room_id: str) -> None:
        await websocket.accept()
        if room_id not in self._rooms:
            self._rooms[room_id] = set()
        self._rooms[room_id].add(websocket)
        self._send_locks.setdefault(websocket, asyncio.Lock())
        logger.info("WS connect room=%s total=%s", room_id, len(self._rooms[room_id]))

    def disconnect(self, websocket: WebSocket, room_id: str) -> None:
        if room_id in self._rooms:
            self._rooms[room_id].discard(websocket)
            if not self._rooms[room_id]:
                del self._rooms[room_id]
        self._send_locks.pop(websocket, None)

    async def broadcast(self, room_id: str, data: dict) -> None:
        if room_id not in self._rooms:
            return
        payload = json.dumps(data)
        dead = set()
        for ws in list(self._rooms[room_id]):
            try:
                lock = self._send_locks.setdefault(ws, asyncio.Lock())
                async with lock:
                    await ws.send_text(payload)
            except Exception:
                logger.warning("WS broadcast failed room=%s", room_id, exc_info=True)
                dead.add(ws)
        for ws in dead:
            self._rooms[room_id].discard(ws)
            self._send_locks.pop(ws, None)

    async def close_room(
        self,
        room_id: str,
        data: dict | None = None,
        *,
        close_code: int = 4404,
    ) -> None:
        if room_id not in self._rooms:
            return
        payload = json.dumps(data) if data else None
        sockets = list(self._rooms.get(room_id, set()))
        for ws in sockets:
            lock = self._send_locks.setdefault(ws, asyncio.Lock())
            try:
                async with lock:
                    if payload:
                        await ws.send_text(payload)
                    await ws.close(code=close_code)
            except Exception:
                logger.warning("WS close failed room=%s", room_id, exc_info=True)
            finally:
                self._rooms.get(room_id, set()).discard(ws)
                self._send_locks.pop(ws, None)
        if room_id in self._rooms and not self._rooms[room_id]:
            del self._rooms[room_id]


manager = ConnectionManager()
lifecycle_manager = ConnectionManager()


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


def run_to_dict(run: CollaborationRun) -> dict:
    return {
        "type": "run_update",
        "id": run.id,
        "room_id": run.room_id,
        "root_message_id": run.root_message_id,
        "initiator_type": run.initiator_type,
        "mode": run.mode,
        "status": run.status,
        "step_count": run.step_count,
        "review_round_count": run.review_round_count,
        "max_steps": run.max_steps,
        "max_review_rounds": run.max_review_rounds,
        "stop_reason": run.stop_reason,
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "updated_at": run.updated_at.isoformat() if run.updated_at else None,
    }


def artifact_to_dict(artifact: AgentArtifact) -> dict:
    return {
        "type": "artifact",
        "id": artifact.id,
        "run_id": artifact.run_id,
        "room_id": artifact.room_id,
        "source_message_id": artifact.source_message_id,
        "agent_name": artifact.agent_name,
        "artifact_type": artifact.artifact_type,
        "title": artifact.title,
        "content": artifact.content,
        "status": artifact.status,
        "created_at": artifact.created_at.isoformat() if artifact.created_at else None,
    }


def run_step_to_dict(step: RunStep) -> dict:
    return {
        "type": "run_step",
        "id": step.id,
        "run_id": step.run_id,
        "room_id": step.room_id,
        "source_message_id": step.source_message_id,
        "agent_name": step.agent_name,
        "step_type": step.step_type,
        "status": step.status,
        "title": step.title,
        "content": step.content,
        "metadata_json": step.metadata_json,
        "created_at": step.created_at.isoformat() if step.created_at else None,
        "updated_at": step.updated_at.isoformat() if step.updated_at else None,
    }


def agent_event_to_dict(event: AgentEvent) -> dict:
    return {
        "type": "agent_event",
        "id": event.id,
        "run_id": event.run_id,
        "room_id": event.room_id,
        "step_id": event.step_id,
        "source_message_id": event.source_message_id,
        "agent_name": event.agent_name,
        "event_type": event.event_type,
        "content": event.content,
        "payload_json": event.payload_json,
        "created_at": event.created_at.isoformat() if event.created_at else None,
    }


def approval_to_dict(approval: ApprovalRequest) -> dict:
    return {
        "type": "approval_request",
        "id": approval.id,
        "run_id": approval.run_id,
        "room_id": approval.room_id,
        "step_id": approval.step_id,
        "source_message_id": approval.source_message_id,
        "agent_name": approval.agent_name,
        "requested_permission_mode": approval.requested_permission_mode,
        "status": approval.status,
        "reason": approval.reason,
        "resume_kind": approval.resume_kind,
        "resume_payload": approval.resume_payload,
        "error_text": approval.error_text,
        "created_at": approval.created_at.isoformat() if approval.created_at else None,
        "resolved_at": approval.resolved_at.isoformat() if approval.resolved_at else None,
    }


def room_created_to_dict(room: Room) -> dict:
    return {
        "type": "room_created",
        "id": room.id,
        "name": room.name,
        "description": room.description,
        "created_at": room.created_at.isoformat() if room.created_at else None,
    }


def room_deleted_to_dict(room_id: str, name: str | None = None) -> dict:
    return {
        "type": "room_deleted",
        "room_id": room_id,
        "name": name,
    }


@router.websocket("/ws/lifecycle/rooms")
async def room_lifecycle_websocket(websocket: WebSocket):
    await lifecycle_manager.connect(websocket, ROOM_LIFECYCLE_CHANNEL)

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if data.get("type") == "ping":
                await websocket.send_text(json.dumps({"type": "pong"}))
    except WebSocketDisconnect:
        lifecycle_manager.disconnect(websocket, ROOM_LIFECYCLE_CHANNEL)
    except Exception as e:
        logger.error("Room lifecycle WebSocket error: %s", e, exc_info=True)
        lifecycle_manager.disconnect(websocket, ROOM_LIFECYCLE_CHANNEL)


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

                        async def on_run_update(run: CollaborationRun):
                            await manager.broadcast(room_id, run_to_dict(run))

                        async def on_artifact(artifact: AgentArtifact):
                            await manager.broadcast(room_id, artifact_to_dict(artifact))

                        async def on_run_step(step: RunStep):
                            await manager.broadcast(room_id, run_step_to_dict(step))

                        async def on_agent_event(event: AgentEvent):
                            await manager.broadcast(room_id, agent_event_to_dict(event))

                        async def on_approval(approval: ApprovalRequest):
                            await manager.broadcast(room_id, approval_to_dict(approval))

                        await route_message(
                            message,
                            db,
                            on_response=on_agent_response,
                            on_status=on_agent_status,
                            on_stream=on_agent_stream,
                            on_run_update=on_run_update,
                            on_artifact=on_artifact,
                            on_step=on_run_step,
                            on_event=on_agent_event,
                            on_approval=on_approval,
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
