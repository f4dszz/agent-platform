from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_memory import AgentMemory
from app.models.message import Message
from app.models.room import Room

MAX_MEMORY_LINES = 48
MAX_MEMORY_LINE_LENGTH = 240


async def get_or_create_agent_memory(
    db: AsyncSession,
    room_id: str,
    agent_name: str,
) -> AgentMemory:
    result = await db.execute(
        select(AgentMemory).where(
            AgentMemory.room_id == room_id,
            AgentMemory.agent_name == agent_name,
        )
    )
    memory = result.scalar_one_or_none()
    if memory:
        return memory

    memory = AgentMemory(room_id=room_id, agent_name=agent_name)
    db.add(memory)
    await db.flush()
    return memory


def _clip_text(value: str, max_length: int = MAX_MEMORY_LINE_LENGTH) -> str:
    normalized = " ".join(value.split())
    if len(normalized) <= max_length:
        return normalized
    return normalized[: max_length - 3].rstrip() + "..."


def _build_memory_line(message: Message) -> str:
    return f"- [{message.sender_name}] {_clip_text(message.content)}"


def _merge_memory_lines(existing_summary: str | None, new_lines: list[str]) -> str | None:
    existing_lines = [line for line in (existing_summary or "").splitlines() if line.strip()]
    merged = existing_lines + [line for line in new_lines if line.strip()]
    if not merged:
        return None
    return "\n".join(merged[-MAX_MEMORY_LINES:])


async def refresh_agent_memory_summary(
    db: AsyncSession,
    room_id: str,
    agent_name: str,
    max_recent_messages: int,
) -> AgentMemory:
    memory = await get_or_create_agent_memory(db, room_id, agent_name)
    total_result = await db.execute(
        select(func.count(Message.id)).where(Message.room_id == room_id)
    )
    total_messages = int(total_result.scalar() or 0)
    summarizable_count = max(total_messages - max_recent_messages, 0)

    if summarizable_count <= memory.summary_message_count:
        return memory

    result = await db.execute(
        select(Message)
        .where(Message.room_id == room_id)
        .order_by(Message.created_at.asc())
        .offset(memory.summary_message_count)
        .limit(summarizable_count - memory.summary_message_count)
    )
    summary_lines = [_build_memory_line(message) for message in result.scalars().all()]
    memory.memory_summary = _merge_memory_lines(memory.memory_summary, summary_lines)
    memory.summary_message_count = summarizable_count
    memory.updated_at = datetime.now(timezone.utc)
    await db.flush()
    return memory


async def build_agent_memory_context(
    db: AsyncSession,
    room_id: str,
    agent_name: str,
    max_recent_messages: int,
) -> str:
    memory = await refresh_agent_memory_summary(db, room_id, agent_name, max_recent_messages)
    room_result = await db.execute(select(Room).where(Room.id == room_id))
    room = room_result.scalar_one_or_none()

    sections: list[str] = []
    if room and room.description:
        sections.append("Room brief:")
        sections.append(room.description.strip())
    if memory.pinned_memory:
        sections.append("Pinned long-term memory:")
        sections.append(memory.pinned_memory.strip())
    if memory.memory_summary:
        sections.append("Earlier room context summary:")
        sections.append(memory.memory_summary.strip())

    return "\n\n".join(section for section in sections if section.strip())


async def sync_agent_memory_from_runtime(
    db: AsyncSession,
    room_id: str,
    agent_name: str,
    provider_session_id: str | None,
    message_count: int,
    estimated_tokens: int,
) -> AgentMemory:
    memory = await get_or_create_agent_memory(db, room_id, agent_name)
    memory.provider_session_id = provider_session_id
    memory.message_count = message_count
    memory.estimated_tokens = estimated_tokens
    memory.last_active_at = datetime.now(timezone.utc)
    memory.updated_at = datetime.now(timezone.utc)
    await db.flush()
    return memory
