from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.models.room import Room
from app.schemas.schemas import RoomCreate, RoomResponse, RoomList
from app.ws.handler import lifecycle_manager, manager, room_created_to_dict, room_deleted_to_dict, ROOM_LIFECYCLE_CHANNEL

router = APIRouter()


class BatchDeleteRequest(BaseModel):
    room_ids: list[str]


@router.post("/", response_model=RoomResponse, status_code=201)
async def create_room(body: RoomCreate, db: AsyncSession = Depends(get_db)):
    """Create a new chat room."""
    room = Room(name=body.name, description=body.description)
    db.add(room)
    await db.flush()
    await db.commit()
    await db.refresh(room)
    await lifecycle_manager.broadcast(
        ROOM_LIFECYCLE_CHANNEL,
        room_created_to_dict(room),
    )
    return room


@router.get("/", response_model=RoomList)
async def list_rooms(db: AsyncSession = Depends(get_db)):
    """List all chat rooms."""
    result = await db.execute(select(Room).order_by(Room.created_at.desc()))
    rooms = list(result.scalars().all())
    count_result = await db.execute(select(func.count(Room.id)))
    total = count_result.scalar() or 0
    return RoomList(rooms=rooms, total=total)


@router.post("/batch-delete", status_code=204)
async def batch_delete_rooms(body: BatchDeleteRequest, db: AsyncSession = Depends(get_db)):
    """Delete multiple rooms at once."""
    if not body.room_ids:
        return
    result = await db.execute(select(Room).where(Room.id.in_(body.room_ids)))
    rooms_to_delete = list(result.scalars().all())
    for room in rooms_to_delete:
        deleted_payload = room_deleted_to_dict(room.id, room.name)
        await db.delete(room)
        await lifecycle_manager.broadcast(ROOM_LIFECYCLE_CHANNEL, deleted_payload)
    await db.commit()
    for room in rooms_to_delete:
        await manager.close_room(
            room.id,
            {"type": "error", "content": "Room deleted"},
            close_code=4404,
        )


@router.get("/{room_id}", response_model=RoomResponse)
async def get_room(room_id: str, db: AsyncSession = Depends(get_db)):
    """Get a specific room by ID."""
    result = await db.execute(select(Room).where(Room.id == room_id))
    room = result.scalar_one_or_none()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    return room


@router.delete("/{room_id}", status_code=204)
async def delete_room(room_id: str, db: AsyncSession = Depends(get_db)):
    """Delete a room and all its messages."""
    result = await db.execute(select(Room).where(Room.id == room_id))
    room = result.scalar_one_or_none()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    deleted_payload = room_deleted_to_dict(room.id, room.name)
    await db.delete(room)
    await db.commit()
    await lifecycle_manager.broadcast(ROOM_LIFECYCLE_CHANNEL, deleted_payload)
    await manager.close_room(
        room_id,
        {"type": "error", "content": "Room deleted"},
        close_code=4404,
    )
