import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class AgentMemory(Base):
    __tablename__ = "agent_memories"
    __table_args__ = (
        UniqueConstraint("room_id", "agent_name", name="uq_agent_memory_room_agent"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    room_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("rooms.id", ondelete="CASCADE"), nullable=False, index=True
    )
    agent_name: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    provider_session_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    message_count: Mapped[int] = mapped_column(Integer, default=0)
    estimated_tokens: Mapped[int] = mapped_column(Integer, default=0)
    summary_message_count: Mapped[int] = mapped_column(Integer, default=0)
    memory_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    pinned_memory: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    last_active_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )

    room: Mapped["Room"] = relationship(back_populates="agent_memories")  # noqa: F821

    def __repr__(self) -> str:
        return f"<AgentMemory room={self.room_id} agent={self.agent_name}>"
