import { useState, useCallback, useEffect, type SetStateAction } from "react";
import type { Message, WSIncomingMessage, Agent } from "../types";
import { useWebSocket } from "../hooks/useWebSocket";
import { listMessages, listAgents } from "../services/api";
import MessageList from "./MessageList";
import MessageInput from "./MessageInput";

type AgentStatuses = Record<string, "idle" | "working" | "offline">;

interface ChatRoomProps {
  roomId: string;
  roomName: string;
  onAgentStatusChange: (update: SetStateAction<AgentStatuses>) => void;
}

export default function ChatRoom({
  roomId,
  roomName,
  onAgentStatusChange,
}: ChatRoomProps) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [agents, setAgents] = useState<Agent[]>([]);

  // Load history on room change
  useEffect(() => {
    let cancelled = false;
    listMessages(roomId).then((data) => {
      if (!cancelled) setMessages(data.messages);
    });
    listAgents().then((data) => {
      if (!cancelled) setAgents(data);
    });
    return () => {
      cancelled = true;
    };
  }, [roomId]);

  // Handle incoming WebSocket messages
  const handleWSMessage = useCallback(
    (msg: WSIncomingMessage) => {
      switch (msg.type) {
        case "chat":
          setMessages((prev) => {
            // Deduplicate by message ID
            if (msg.id && prev.some((m) => m.id === msg.id)) return prev;
            return [
              ...prev,
              {
                id: msg.id,
                room_id: msg.room_id,
                sender_type: msg.sender_type as Message["sender_type"],
                sender_name: msg.sender_name,
                content: msg.content,
                created_at: msg.created_at,
              },
            ];
          });
          break;

        case "status":
          onAgentStatusChange((prev) => ({
            ...prev,
            [msg.agent_name]: msg.status,
          }));
          break;

        case "error":
          console.error("[Chat] Server error:", msg.content);
          break;
      }
    },
    [onAgentStatusChange]
  );

  const { connected, send } = useWebSocket({
    roomId,
    onMessage: handleWSMessage,
  });

  const handleSend = (content: string) => {
    send({
      type: "chat",
      sender_name: "User",
      content,
    });
  };

  return (
    <div className="flex flex-col h-full">
      {/* Room header */}
      <div className="px-4 py-3 border-b border-gray-700 bg-gray-800 flex items-center justify-between">
        <div>
          <h2 className="text-white font-semibold"># {roomName}</h2>
        </div>
        <div className="flex items-center gap-2">
          <span
            className={`w-2 h-2 rounded-full ${
              connected ? "bg-green-400" : "bg-red-400"
            }`}
          />
          <span className="text-xs text-gray-400">
            {connected ? "Connected" : "Reconnecting..."}
          </span>
        </div>
      </div>

      {/* Messages */}
      <MessageList messages={messages} />

      {/* Input */}
      <MessageInput
        onSend={handleSend}
        disabled={!connected}
        agentNames={agents.filter((a) => a.enabled).map((a) => a.name)}
      />
    </div>
  );
}
