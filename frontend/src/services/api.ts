// ── REST API client ──────────────────────────────────────────────────────────

import type {
  Agent,
  AgentCapabilities,
  AgentArtifact,
  AgentEvent,
  ApprovalRequest,
  CollaborationRun,
  Room,
  RunStep,
  Message,
} from "../types";

const API_BASE = "/api";

async function request<T>(
  path: string,
  options?: RequestInit
): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });

  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(error.detail || `HTTP ${res.status}`);
  }

  if (res.status === 204) return undefined as T;
  return res.json();
}

// ── Rooms ────────────────────────────────────────────────────────────────────

export async function listRooms(): Promise<{ rooms: Room[]; total: number }> {
  return request("/rooms/");
}

export async function createRoom(
  name: string,
  description?: string
): Promise<Room> {
  return request("/rooms/", {
    method: "POST",
    body: JSON.stringify({ name, description }),
  });
}

export async function getRoom(roomId: string): Promise<Room> {
  return request(`/rooms/${roomId}`);
}

export async function deleteRoom(roomId: string): Promise<void> {
  return request(`/rooms/${roomId}`, { method: "DELETE" });
}

export async function batchDeleteRooms(roomIds: string[]): Promise<void> {
  return request(`/rooms/batch-delete`, {
    method: "POST",
    body: JSON.stringify({ room_ids: roomIds }),
  });
}

// ── Messages ─────────────────────────────────────────────────────────────────

export async function listMessages(
  roomId: string,
  limit = 50,
  offset = 0
): Promise<{ messages: Message[]; total: number }> {
  return request(`/messages/${roomId}?limit=${limit}&offset=${offset}`);
}

// ── Agents ───────────────────────────────────────────────────────────────────

export async function listAgents(): Promise<Agent[]> {
  return request("/agents/");
}

export async function getAgentCapabilities(agentName: string): Promise<AgentCapabilities> {
  return request(`/agents/${agentName}/capabilities`);
}

export async function listRoomRuns(
  roomId: string,
  limit = 20,
  offset = 0
): Promise<{ runs: CollaborationRun[]; total: number }> {
  return request(`/collaboration/rooms/${roomId}/runs?limit=${limit}&offset=${offset}`);
}

export async function updateRunLimits(
  runId: string,
  limits: { max_steps?: number; max_review_rounds?: number }
): Promise<CollaborationRun> {
  return request(`/collaboration/runs/${runId}/limits`, {
    method: "PATCH",
    body: JSON.stringify(limits),
  });
}

export async function listRoomArtifacts(
  roomId: string,
  limit = 200,
  offset = 0
): Promise<{ artifacts: AgentArtifact[]; total: number }> {
  return request(`/collaboration/rooms/${roomId}/artifacts?limit=${limit}&offset=${offset}`);
}

export async function listRoomSteps(
  roomId: string,
  limit = 200,
  offset = 0
): Promise<{ steps: RunStep[]; total: number }> {
  return request(`/collaboration/rooms/${roomId}/steps?limit=${limit}&offset=${offset}`);
}

export async function listRoomEvents(
  roomId: string,
  limit = 300,
  offset = 0
): Promise<{ events: AgentEvent[]; total: number }> {
  return request(`/collaboration/rooms/${roomId}/events?limit=${limit}&offset=${offset}`);
}

export async function listRoomApprovals(
  roomId: string,
  limit = 100,
  offset = 0
): Promise<{ approvals: ApprovalRequest[]; total: number }> {
  return request(`/collaboration/rooms/${roomId}/approvals?limit=${limit}&offset=${offset}`);
}

export async function approveApproval(approvalId: string): Promise<ApprovalRequest> {
  return request(`/collaboration/approvals/${approvalId}/approve`, { method: "POST" });
}

export async function denyApproval(approvalId: string): Promise<ApprovalRequest> {
  return request(`/collaboration/approvals/${approvalId}/deny`, { method: "POST" });
}

export async function registerAgent(agent: {
  name: string;
  display_name: string;
  agent_type: "claude" | "codex";
  command: string;
  model?: string | null;
  reasoning_effort?: string | null;
  default_args?: string;
  max_timeout?: number;
  avatar_label?: string | null;
  avatar_color?: string | null;
}): Promise<Agent> {
  return request("/agents/", {
    method: "POST",
    body: JSON.stringify(agent),
  });
}

export async function toggleAgent(agentName: string): Promise<Agent> {
  return request(`/agents/${agentName}/toggle`, { method: "PATCH" });
}

export async function updateAgent(
  agentName: string,
  fields: {
    display_name?: string;
    command?: string;
    model?: string | null;
    reasoning_effort?: string | null;
    default_args?: string | null;
    permission_mode?: string;
    allowed_tools?: string | null;
    avatar_label?: string | null;
    avatar_color?: string | null;
    system_prompt?: string | null;
    max_timeout?: number;
  }
): Promise<Agent> {
  return request(`/agents/${agentName}`, {
    method: "PATCH",
    body: JSON.stringify(fields),
  });
}
