from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.models.message import Message
from app.models.room import Room
from app.schemas.schemas import MessageCreate, MessageResponse, MessageList

router = APIRouter()


@router.post("/", response_model=MessageResponse, status_code=201)
async def send_message(body: MessageCreate, db: AsyncSession = Depends(get_db)):
    """Send a message to a room (from the REST API — mainly for testing).

    In normal flow, messages come through WebSocket and the orchestrator.
    """
    # Verify room exists
    result = await db.execute(select(Room).where(Room.id == body.room_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Room not found")

    message = Message(
        room_id=body.room_id,
        sender_type="human",
        sender_name=body.sender_name,
        content=body.content,
    )
    db.add(message)
    await db.flush()
    await db.refresh(message)
    return message


@router.get("/{room_id}", response_model=MessageList)
async def list_messages(
    room_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """List messages in a room with pagination (newest first)."""
    # Verify room exists
    result = await db.execute(select(Room).where(Room.id == room_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Room not found")

    # Get messages
    stmt = (
        select(Message)
        .where(Message.room_id == room_id)
        .order_by(Message.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    result = await db.execute(stmt)
    messages = list(result.scalars().all())

    # Total count
    count_result = await db.execute(
        select(func.count(Message.id)).where(Message.room_id == room_id)
    )
    total = count_result.scalar() or 0

    # Return in chronological order for display
    messages.reverse()
    return MessageList(messages=messages, total=total)
