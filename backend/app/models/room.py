import uuid
from datetime import datetime, timezone

from sqlalchemy import String, DateTime, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class Room(Base):
    __tablename__ = "rooms"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    messages: Mapped[list["Message"]] = relationship(  # noqa: F821
        back_populates="room", cascade="all, delete-orphan", lazy="selectin"
    )
    agent_memories: Mapped[list["AgentMemory"]] = relationship(  # noqa: F821
        back_populates="room", cascade="all, delete-orphan", lazy="selectin"
    )
    collaboration_runs: Mapped[list["CollaborationRun"]] = relationship(  # noqa: F821
        back_populates="room", cascade="all, delete-orphan", lazy="selectin"
    )
    agent_artifacts: Mapped[list["AgentArtifact"]] = relationship(  # noqa: F821
        back_populates="room", cascade="all, delete-orphan", lazy="selectin"
    )

    def __repr__(self) -> str:
        return f"<Room {self.name}>"
