import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class CollaborationRun(Base):
    __tablename__ = "collaboration_runs"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    room_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("rooms.id", ondelete="CASCADE"), nullable=False, index=True
    )
    root_message_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("messages.id", ondelete="CASCADE"), nullable=False, index=True
    )
    initiator_type: Mapped[str] = mapped_column(String(20), nullable=False)
    mode: Mapped[str] = mapped_column(String(50), default="custom", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="running", nullable=False, index=True)
    step_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    review_round_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_steps: Mapped[int] = mapped_column(Integer, default=6, nullable=False)
    max_review_rounds: Mapped[int] = mapped_column(Integer, default=2, nullable=False)
    stop_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    room: Mapped["Room"] = relationship(back_populates="collaboration_runs")  # noqa: F821
    artifacts: Mapped[list["AgentArtifact"]] = relationship(  # noqa: F821
        back_populates="run", cascade="all, delete-orphan", lazy="selectin"
    )
    steps: Mapped[list["RunStep"]] = relationship(  # noqa: F821
        back_populates="run", cascade="all, delete-orphan", lazy="selectin"
    )
    events: Mapped[list["AgentEvent"]] = relationship(  # noqa: F821
        back_populates="run", cascade="all, delete-orphan", lazy="selectin"
    )
    approval_requests: Mapped[list["ApprovalRequest"]] = relationship(  # noqa: F821
        back_populates="run", cascade="all, delete-orphan", lazy="selectin"
    )

    def __repr__(self) -> str:
        return f"<CollaborationRun room={self.room_id} status={self.status} mode={self.mode}>"
