import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class AgentArtifact(Base):
    __tablename__ = "agent_artifacts"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("collaboration_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    room_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("rooms.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_message_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("messages.id", ondelete="CASCADE"), nullable=False, index=True
    )
    agent_name: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    artifact_type: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )

    run: Mapped["CollaborationRun"] = relationship(back_populates="artifacts")  # noqa: F821
    room: Mapped["Room"] = relationship(back_populates="agent_artifacts")  # noqa: F821

    def __repr__(self) -> str:
        return (
            f"<AgentArtifact run={self.run_id} agent={self.agent_name} "
            f"type={self.artifact_type}>"
        )
