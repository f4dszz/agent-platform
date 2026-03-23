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
    model: str | None = Field(default=None, max_length=120)
    reasoning_effort: str | None = Field(default=None, max_length=20)
    default_args: str | None = None
    max_timeout: int = Field(default=300, ge=10, le=3600)
    permission_mode: str = Field(default="acceptEdits", max_length=30)
    allowed_tools: str | None = None
    avatar_label: str | None = Field(default=None, max_length=8)
    avatar_color: str | None = Field(default=None, max_length=40)
    system_prompt: str | None = None


class AgentUpdate(BaseModel):
    display_name: str | None = None
    command: str | None = Field(default=None, max_length=500)
    model: str | None = Field(default=None, max_length=120)
    reasoning_effort: str | None = Field(default=None, max_length=20)
    default_args: str | None = None
    permission_mode: str | None = None
    allowed_tools: str | None = None
    avatar_label: str | None = Field(default=None, max_length=8)
    avatar_color: str | None = Field(default=None, max_length=40)
    system_prompt: str | None = None
    max_timeout: int | None = Field(default=None, ge=10, le=3600)


class AgentResponse(BaseModel):
    id: str
    name: str
    display_name: str
    agent_type: str
    command: str
    model: str | None
    reasoning_effort: str | None
    default_args: str | None
    enabled: bool
    max_timeout: int
    permission_mode: str
    allowed_tools: str | None
    avatar_label: str | None
    avatar_color: str | None
    system_prompt: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class AgentConfigOption(BaseModel):
    value: str
    label: str
    description: str | None = None


class AgentCapabilitiesResponse(BaseModel):
    agent_name: str
    agent_type: str
    model_placeholder: str
    model_help: str | None = None
    model_options: list[AgentConfigOption]
    reasoning_supported: bool = False
    reasoning_label: str | None = None
    reasoning_help: str | None = None
    reasoning_options: list[AgentConfigOption] = Field(default_factory=list)
    execution_label: str
    execution_help: str | None = None
    execution_options: list[AgentConfigOption]
    tool_rules_supported: bool = False
    tool_rules_label: str | None = None
    tool_rules_help: str | None = None
    tool_rules_placeholder: str | None = None
    advanced_fields: list[str] = Field(default_factory=list)


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


class CollaborationRunResponse(BaseModel):
    id: str
    room_id: str
    root_message_id: str
    initiator_type: str
    mode: str
    status: str
    step_count: int
    review_round_count: int
    max_steps: int
    max_review_rounds: int
    stop_reason: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class CollaborationRunList(BaseModel):
    runs: list[CollaborationRunResponse]
    total: int


class AgentArtifactResponse(BaseModel):
    id: str
    run_id: str
    room_id: str
    source_message_id: str
    agent_name: str
    artifact_type: str
    title: str | None
    content: str
    status: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class AgentArtifactList(BaseModel):
    artifacts: list[AgentArtifactResponse]
    total: int


class RunStepResponse(BaseModel):
    id: str
    run_id: str
    room_id: str
    source_message_id: str | None
    agent_name: str | None
    step_type: str
    status: str
    title: str | None
    content: str | None
    metadata_json: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class RunStepList(BaseModel):
    steps: list[RunStepResponse]
    total: int


class AgentEventResponse(BaseModel):
    id: str
    run_id: str
    room_id: str
    step_id: str | None
    source_message_id: str | None
    agent_name: str | None
    event_type: str
    content: str | None
    payload_json: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class AgentEventList(BaseModel):
    events: list[AgentEventResponse]
    total: int


class ApprovalRequestResponse(BaseModel):
    id: str
    run_id: str
    room_id: str
    step_id: str | None
    source_message_id: str | None
    agent_name: str
    requested_permission_mode: str
    status: str
    reason: str
    resume_kind: str | None
    resume_payload: str | None
    error_text: str | None
    created_at: datetime
    resolved_at: datetime | None

    model_config = {"from_attributes": True}


class ApprovalRequestList(BaseModel):
    approvals: list[ApprovalRequestResponse]
    total: int
