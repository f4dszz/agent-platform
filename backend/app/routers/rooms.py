from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.models.room import Room
from app.schemas.schemas import RoomCreate, RoomResponse, RoomList

router = APIRouter()


@router.post("/", response_model=RoomResponse, status_code=201)
async def create_room(body: RoomCreate, db: AsyncSession = Depends(get_db)):
    """Create a new chat room."""
    room = Room(name=body.name, description=body.description)
    db.add(room)
    await db.flush()
    await db.refresh(room)
    return room


@router.get("/", response_model=RoomList)
async def list_rooms(db: AsyncSession = Depends(get_db)):
    """List all chat rooms."""
    result = await db.execute(select(Room).order_by(Room.created_at.desc()))
    rooms = list(result.scalars().all())
    count_result = await db.execute(select(func.count(Room.id)))
    total = count_result.scalar() or 0
    return RoomList(rooms=rooms, total=total)


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
    await db.delete(room)
