import { useCallback, useEffect, useState, type SetStateAction } from "react";
import type {
  Agent,
  AgentArtifact,
  AgentEvent,
  ApprovalRequest,
  CollaborationRun,
  Message,
  RunStep,
  WSIncomingMessage,
} from "../types";
import { useWebSocket } from "../hooks/useWebSocket";
import {
  approveApproval,
  denyApproval,
  listAgents,
  listMessages,
  listRoomApprovals,
  listRoomArtifacts,
  listRoomEvents,
  listRoomRuns,
  listRoomSteps,
} from "../services/api";
import { useTheme, t } from "./ThemeContext";
import MessageInput from "./MessageInput";
import MessageList from "./MessageList";
import RunTimeline from "./RunTimeline";

type AgentStatuses = Record<string, "idle" | "working" | "offline">;
type ArtifactsByMessage = Record<string, AgentArtifact[]>;

interface ChatRoomProps {
  roomId: string;
  roomName: string;
  agentConfigVersion: number;
  onAgentStatusChange: (update: SetStateAction<AgentStatuses>) => void;
}

function upsertById<T extends { id: string }>(items: T[], next: T): T[] {
  const existingIndex = items.findIndex((item) => item.id === next.id);
  if (existingIndex >= 0) {
    const updated = [...items];
    updated[existingIndex] = { ...updated[existingIndex], ...next };
    return updated;
  }
  return [...items, next];
}

function groupArtifactsByMessage(artifacts: AgentArtifact[]): ArtifactsByMessage {
  return artifacts.reduce<ArtifactsByMessage>((grouped, artifact) => {
    const current = grouped[artifact.source_message_id] ?? [];
    grouped[artifact.source_message_id] = [...current, artifact].sort(
      (left, right) =>
        new Date(left.created_at).getTime() - new Date(right.created_at).getTime()
    );
    return grouped;
  }, {});
}

function mergeArtifactMaps(
  incoming: ArtifactsByMessage,
  existing: ArtifactsByMessage
): ArtifactsByMessage {
  const merged: ArtifactsByMessage = { ...existing };
  for (const [messageId, artifacts] of Object.entries(incoming)) {
    const nextArtifacts = [...(merged[messageId] ?? [])];
    for (const artifact of artifacts) {
      const existingIndex = nextArtifacts.findIndex((item) => item.id === artifact.id);
      if (existingIndex >= 0) nextArtifacts[existingIndex] = { ...nextArtifacts[existingIndex], ...artifact };
      else nextArtifacts.push(artifact);
    }
    merged[messageId] = nextArtifacts.sort(
      (left, right) =>
        new Date(left.created_at).getTime() - new Date(right.created_at).getTime()
    );
  }
  return merged;
}

export default function ChatRoom({
  roomId,
  roomName,
  agentConfigVersion,
  onAgentStatusChange,
}: ChatRoomProps) {
  const { mode } = useTheme();
  const tk = t(mode);
  const [messages, setMessages] = useState<Message[]>([]);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [typingAgents, setTypingAgents] = useState<string[]>([]);
  const [runs, setRuns] = useState<CollaborationRun[]>([]);
  const [artifactsByMessage, setArtifactsByMessage] = useState<ArtifactsByMessage>({});
  const [steps, setSteps] = useState<RunStep[]>([]);
  const [events, setEvents] = useState<AgentEvent[]>([]);
  const [approvals, setApprovals] = useState<ApprovalRequest[]>([]);

  const removeTypingAgent = useCallback((identifier: string) => {
    setTypingAgents((prev) =>
      prev.filter((displayName) => {
        const agent = agents.find((candidate) => candidate.display_name === displayName);
        if (displayName === identifier) return false;
        return agent ? agent.name !== identifier : true;
      })
    );
  }, [agents]);

  const reloadRoomContext = useCallback(() => {
    Promise.all([
      listMessages(roomId),
      listRoomRuns(roomId),
      listRoomArtifacts(roomId),
      listRoomSteps(roomId),
      listRoomEvents(roomId),
      listRoomApprovals(roomId),
    ])
      .then(([messageData, runData, artifactData, stepData, eventData, approvalData]) => {
        setMessages(messageData.messages);
        setRuns(runData.runs.sort((left, right) =>
          new Date(right.created_at).getTime() - new Date(left.created_at).getTime()
        ));
        setArtifactsByMessage(groupArtifactsByMessage(artifactData.artifacts));
        setSteps(stepData.steps);
        setEvents(eventData.events);
        setApprovals(approvalData.approvals);
      })
      .catch((error) => {
        console.error("[Chat] Failed to load room context:", error);
      });
  }, [roomId]);

  useEffect(() => {
    reloadRoomContext();
  }, [reloadRoomContext]);

  useEffect(() => {
    listAgents()
      .then(setAgents)
      .catch((error) => {
        console.error("[Chat] Failed to load agents:", error);
      });
  }, [roomId, agentConfigVersion]);

  const handleWSMessage = useCallback(
    (msg: WSIncomingMessage) => {
      switch (msg.type) {
        case "chat":
          setMessages((prev) => upsertById(prev, { ...msg, streaming: false }));
          break;
        case "stream_chunk":
          removeTypingAgent(msg.sender_name);
          setMessages((prev) => upsertById(prev, { ...msg, streaming: true }));
          break;
        case "status": {
          const name = msg.agent_name;
          const status = msg.status;
          onAgentStatusChange((prev) => ({ ...prev, [name]: status }));
          if (status === "working") {
            const displayName =
              agents.find((agent) => agent.name === name)?.display_name ?? name;
            setTypingAgents((prev) => (prev.includes(displayName) ? prev : [...prev, displayName]));
          } else {
            removeTypingAgent(name);
          }
          break;
        }
        case "run_update":
          setRuns((prev) =>
            upsertById(prev, msg).sort(
              (left, right) =>
                new Date(right.created_at).getTime() - new Date(left.created_at).getTime()
            )
          );
          break;
        case "artifact":
          setArtifactsByMessage((prev) =>
            mergeArtifactMaps({ [msg.source_message_id]: [msg] }, prev)
          );
          break;
        case "run_step":
          setSteps((prev) =>
            upsertById(prev, msg).sort(
              (left, right) =>
                new Date(left.created_at).getTime() - new Date(right.created_at).getTime()
            )
          );
          break;
        case "agent_event":
          setEvents((prev) =>
            upsertById(prev, msg).sort(
              (left, right) =>
                new Date(left.created_at).getTime() - new Date(right.created_at).getTime()
            )
          );
          break;
        case "approval_request":
          setApprovals((prev) =>
            upsertById(prev, msg).sort(
              (left, right) =>
                new Date(left.created_at).getTime() - new Date(right.created_at).getTime()
            )
          );
          break;
        case "error":
          console.error("[Chat] Server error:", msg.content);
          break;
      }
    },
    [agents, onAgentStatusChange, removeTypingAgent]
  );

  const { connected, send } = useWebSocket({
    roomId,
    onMessage: handleWSMessage,
  });

  return (
    <div className={`flex flex-col h-full ${tk.bg}`}>
      <div className={`px-5 py-3.5 border-b ${tk.borderLight} ${tk.bgSecondary}/80 backdrop-blur flex items-center justify-between`}>
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-sky-500 to-cyan-600 flex items-center justify-center text-white text-sm font-bold shadow-sm">
            #
          </div>
          <h2 className={`${tk.text} font-semibold text-sm`}>{roomName}</h2>
        </div>
        <div className="flex items-center gap-2">
          <span
            className={`w-2 h-2 rounded-full transition-colors ${
              connected ? "bg-green-400 shadow-[0_0_6px_rgba(74,222,128,0.4)]" : "bg-red-400"
            }`}
          />
          <span className={`text-xs ${tk.textMuted}`}>
            {connected ? "Connected" : "Reconnecting..."}
          </span>
        </div>
      </div>

      <RunTimeline
        runs={runs}
        steps={steps}
        events={events}
        approvals={approvals}
        agents={agents}
        onJumpToMessage={(messageId) => {
          document.getElementById(`message-${messageId}`)?.scrollIntoView({
            behavior: "smooth",
            block: "center",
          });
        }}
        onApprove={async (approvalId) => {
          const approval = await approveApproval(approvalId);
          setApprovals((prev) => upsertById(prev, approval));
        }}
        onDeny={async (approvalId) => {
          const approval = await denyApproval(approvalId);
          setApprovals((prev) => upsertById(prev, approval));
        }}
        onRunUpdated={(updated) => {
          setRuns((prev) => upsertById(prev, updated));
        }}
      />

      <MessageList
        messages={messages}
        typingAgents={typingAgents}
        artifactsByMessage={artifactsByMessage}
        agents={agents}
      />

      <MessageInput
        onSend={(content) => send({ type: "chat", sender_name: "User", content })}
        disabled={!connected}
        agentNames={agents.filter((agent) => agent.enabled).map((agent) => agent.name)}
      />
    </div>
  );
}
