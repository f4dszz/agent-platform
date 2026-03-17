from datetime import datetime
from pydantic import BaseModel, Field


# ── Room Schemas ──────────────────────────────────────────────────────────────


class RoomCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None


class RoomResponse(BaseModel):
    id: str
    name: str
    description: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class RoomList(BaseModel):
    rooms: list[RoomResponse]
    total: int


# ── Message Schemas ───────────────────────────────────────────────────────────


class MessageCreate(BaseModel):
    room_id: str
    sender_name: str = Field(default="User", max_length=100)
    content: str = Field(..., min_length=1)


class MessageResponse(BaseModel):
    id: str
    room_id: str
    sender_type: str
    sender_name: str
    content: str
    created_at: datetime

    model_config = {"from_attributes": True}


class MessageList(BaseModel):
    messages: list[MessageResponse]
    total: int


# ── Agent Schemas ─────────────────────────────────────────────────────────────


class AgentRegister(BaseModel):
    name: str = Field(..., min_length=1, max_length=50)
    display_name: str = Field(..., max_length=100)
    agent_type: str = Field(..., pattern=r"^(claude|codex)$")
    command: str = Field(..., max_length=500)
    default_args: str | None = None
    max_timeout: int = Field(default=300, ge=10, le=3600)


class AgentResponse(BaseModel):
    id: str
    name: str
    display_name: str
    agent_type: str
    command: str
    default_args: str | None
    enabled: bool
    max_timeout: int
    created_at: datetime

    model_config = {"from_attributes": True}


class AgentStatusResponse(BaseModel):
    name: str
    display_name: str
    status: str  # "idle", "working", "offline"
    current_session_id: str | None = None
    message_count: int = 0


# ── WebSocket Schemas ─────────────────────────────────────────────────────────


class WSMessage(BaseModel):
    """Message sent/received over WebSocket."""

    type: str  # "chat", "status", "stream_chunk", "error"
    room_id: str | None = None
    sender_name: str | None = None
    content: str | None = None
    agent_name: str | None = None  # For status updates
    status: str | None = None  # For status updates
