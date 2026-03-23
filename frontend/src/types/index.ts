// ── Shared TypeScript types ──────────────────────────────────────────────────

export interface Room {
  id: string;
  name: string;
  description: string | null;
  created_at: string;
}

export interface Message {
  id: string;
  room_id: string;
  sender_type: "human" | "claude" | "codex" | "system";
  sender_name: string;
  content: string;
  created_at: string;
  streaming?: boolean;
}

export type MessageSenderType = Message["sender_type"];

export interface Agent {
  id: string;
  name: string;
  display_name: string;
  agent_type: "claude" | "codex";
  command: string;
  model: string | null;
  reasoning_effort: string | null;
  default_args: string | null;
  enabled: boolean;
  max_timeout: number;
  permission_mode: string;
  allowed_tools: string | null;
  avatar_label: string | null;
  avatar_color: string | null;
  system_prompt: string | null;
  created_at: string;
}

export interface AgentConfigOption {
  value: string;
  label: string;
  description: string | null;
}

export interface AgentCapabilities {
  agent_name: string;
  agent_type: "claude" | "codex";
  model_placeholder: string;
  model_help: string | null;
  model_options: AgentConfigOption[];
  reasoning_supported: boolean;
  reasoning_label: string | null;
  reasoning_help: string | null;
  reasoning_options: AgentConfigOption[];
  execution_label: string;
  execution_help: string | null;
  execution_options: AgentConfigOption[];
  tool_rules_supported: boolean;
  tool_rules_label: string | null;
  tool_rules_help: string | null;
  tool_rules_placeholder: string | null;
  advanced_fields: string[];
}

export interface AgentStatus {
  name: string;
  display_name: string;
  status: "idle" | "working" | "offline";
  current_session_id: string | null;
  message_count: number;
}

export interface CollaborationRun {
  id: string;
  room_id: string;
  root_message_id: string;
  initiator_type: string;
  mode: string;
  status: "running" | "blocked" | "completed" | "stopped" | "failed";
  step_count: number;
  review_round_count: number;
  max_steps: number;
  max_review_rounds: number;
  stop_reason: string | null;
  created_at: string;
  updated_at: string;
}

export interface AgentArtifact {
  id: string;
  run_id: string;
  room_id: string;
  source_message_id: string;
  agent_name: string;
  artifact_type: string;
  title: string | null;
  content: string;
  status: string | null;
  created_at: string;
}

export interface RunStep {
  id: string;
  run_id: string;
  room_id: string;
  source_message_id: string | null;
  agent_name: string | null;
  step_type: string;
  status: string;
  title: string | null;
  content: string | null;
  metadata_json: string | null;
  created_at: string;
  updated_at: string;
}

export interface AgentEvent {
  id: string;
  run_id: string;
  room_id: string;
  step_id: string | null;
  source_message_id: string | null;
  agent_name: string | null;
  event_type: string;
  content: string | null;
  payload_json: string | null;
  created_at: string;
}

export interface ApprovalRequest {
  id: string;
  run_id: string;
  room_id: string;
  step_id: string | null;
  source_message_id: string | null;
  agent_name: string;
  requested_permission_mode: string;
  status: "pending" | "approved" | "denied";
  reason: string;
  resume_kind: string | null;
  resume_payload: string | null;
  error_text: string | null;
  created_at: string;
  resolved_at: string | null;
}

// WebSocket message types
export interface WSChatMessage {
  type: "chat";
  id: string;
  room_id: string;
  sender_type: MessageSenderType;
  sender_name: string;
  content: string;
  created_at: string;
}

export interface WSStreamChunkMessage {
  type: "stream_chunk";
  id: string;
  room_id: string;
  sender_type: MessageSenderType;
  sender_name: string;
  content: string;
  created_at: string;
}

export interface WSStatusMessage {
  type: "status";
  agent_name: string;
  status: "idle" | "working" | "offline";
}

export interface WSRunUpdateMessage extends CollaborationRun {
  type: "run_update";
}

export interface WSArtifactMessage extends AgentArtifact {
  type: "artifact";
}

export interface WSRunStepMessage extends RunStep {
  type: "run_step";
}

export interface WSAgentEventMessage extends AgentEvent {
  type: "agent_event";
}

export interface WSApprovalRequestMessage extends ApprovalRequest {
  type: "approval_request";
}

export interface WSErrorMessage {
  type: "error";
  content: string;
}

export interface WSRoomCreatedMessage extends Room {
  type: "room_created";
}

export interface WSRoomDeletedMessage {
  type: "room_deleted";
  room_id: string;
  name: string | null;
}

export type WSIncomingMessage =
  | WSChatMessage
  | WSStreamChunkMessage
  | WSStatusMessage
  | WSRunUpdateMessage
  | WSArtifactMessage
  | WSRunStepMessage
  | WSAgentEventMessage
  | WSApprovalRequestMessage
  | WSErrorMessage;

export type WSRoomLifecycleMessage =
  | WSRoomCreatedMessage
  | WSRoomDeletedMessage
  | WSErrorMessage;

export interface WSOutgoingMessage {
  type: "chat" | "ping";
  sender_name?: string;
  content?: string;
}
