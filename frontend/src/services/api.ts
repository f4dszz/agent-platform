// ── REST API client ──────────────────────────────────────────────────────────

import type { Room, Message, Agent } from "../types";

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

export async function registerAgent(agent: {
  name: string;
  display_name: string;
  agent_type: "claude" | "codex";
  command: string;
  default_args?: string;
  max_timeout?: number;
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
    permission_mode?: string;
    allowed_tools?: string | null;
    system_prompt?: string | null;
    max_timeout?: number;
  }
): Promise<Agent> {
  return request(`/agents/${agentName}`, {
    method: "PATCH",
    body: JSON.stringify(fields),
  });
}
