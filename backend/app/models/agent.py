import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class AgentConfig(Base):
    __tablename__ = "agent_configs"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    name: Mapped[str] = mapped_column(
        String(50), unique=True, nullable=False
    )  # e.g. "claude", "codex"
    display_name: Mapped[str] = mapped_column(
        String(100), nullable=False
    )  # e.g. "Claude Code", "Codex CLI"
    agent_type: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # "claude", "codex"
    command: Mapped[str] = mapped_column(
        String(500), nullable=False
    )  # CLI command path
    model: Mapped[str | None] = mapped_column(
        String(120), nullable=True
    )  # Provider model identifier
    default_args: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )  # JSON string of default arguments
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    max_timeout: Mapped[int] = mapped_column(
        Integer, default=300
    )  # seconds
    permission_mode: Mapped[str] = mapped_column(
        String(30), default="acceptEdits"
    )  # "default", "acceptEdits", "plan", "bypassPermissions"
    allowed_tools: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )  # Comma-separated: "Read,Glob,Grep,Edit,Write,Bash"; null = all
    avatar_label: Mapped[str | None] = mapped_column(
        String(8), nullable=True
    )  # Short text rendered inside the avatar chip
    avatar_color: Mapped[str | None] = mapped_column(
        String(40), nullable=True
    )  # Hex/rgb CSS color used for the avatar background
    system_prompt: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )  # Persona / collaboration prompt
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    def __repr__(self) -> str:
        return f"<AgentConfig {self.name}>"
