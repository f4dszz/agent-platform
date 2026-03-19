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

export interface Agent {
  id: string;
  name: string;
  display_name: string;
  agent_type: "claude" | "codex";
  command: string;
  default_args: string | null;
  enabled: boolean;
  max_timeout: number;
  permission_mode: string;
  allowed_tools: string | null;
  system_prompt: string | null;
  created_at: string;
}

export interface AgentStatus {
  name: string;
  display_name: string;
  status: "idle" | "working" | "offline";
  current_session_id: string | null;
  message_count: number;
}

// WebSocket message types
export interface WSChatMessage {
  type: "chat";
  id: string;
  room_id: string;
  sender_type: string;
  sender_name: string;
  content: string;
  created_at: string;
}

export interface WSStreamChunkMessage {
  type: "stream_chunk";
  id: string;
  room_id: string;
  sender_type: string;
  sender_name: string;
  content: string;
  created_at: string;
}

export interface WSStatusMessage {
  type: "status";
  agent_name: string;
  status: "idle" | "working" | "offline";
}

export interface WSErrorMessage {
  type: "error";
  content: string;
}

export type WSIncomingMessage =
  | WSChatMessage
  | WSStreamChunkMessage
  | WSStatusMessage
  | WSErrorMessage;

export interface WSOutgoingMessage {
  type: "chat" | "ping";
  sender_name?: string;
  content?: string;
}
