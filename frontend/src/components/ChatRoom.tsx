import { useState, useCallback, useEffect, type SetStateAction } from "react";
import type { Message, WSIncomingMessage, Agent } from "../types";
import { useWebSocket } from "../hooks/useWebSocket";
import { listMessages, listAgents } from "../services/api";
import { useTheme, t } from "./ThemeContext";
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
  const { mode } = useTheme();
  const tk = t(mode);
  const [messages, setMessages] = useState<Message[]>([]);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [typingAgents, setTypingAgents] = useState<string[]>([]);

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

  const handleWSMessage = useCallback(
    (msg: WSIncomingMessage) => {
      switch (msg.type) {
        case "chat":
          setMessages((prev) => {
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

        case "status": {
          const name = msg.agent_name;
          const status = msg.status;

          onAgentStatusChange((prev) => ({ ...prev, [name]: status }));

          if (status === "working") {
            // Find display name for the agent
            const displayName =
              agents.find((a) => a.name === name)?.display_name ?? name;
            setTypingAgents((prev) =>
              prev.includes(displayName) ? prev : [...prev, displayName]
            );
          } else {
            // Remove from typing (match by agent name or display name)
            setTypingAgents((prev) =>
              prev.filter((n) => {
                const a = agents.find((ag) => ag.display_name === n);
                return a ? a.name !== name : n !== name;
              })
            );
          }
          break;
        }

        case "error":
          console.error("[Chat] Server error:", msg.content);
          break;
      }
    },
    [onAgentStatusChange, agents]
  );

  const { connected, send } = useWebSocket({
    roomId,
    onMessage: handleWSMessage,
  });

  const handleSend = (content: string) => {
    send({ type: "chat", sender_name: "User", content });
  };

  return (
    <div className={`flex flex-col h-full ${tk.bg}`}>
      {/* Room header */}
      <div className={`px-5 py-3.5 border-b ${tk.borderLight} ${tk.bgSecondary}/80 backdrop-blur flex items-center justify-between`}>
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-violet-500 to-purple-600 flex items-center justify-center text-white text-sm font-bold shadow-sm">
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

      {/* Messages */}
      <MessageList messages={messages} typingAgents={typingAgents} />

      {/* Input */}
      <MessageInput
        onSend={handleSend}
        disabled={!connected}
        agentNames={agents.filter((a) => a.enabled).map((a) => a.name)}
      />
    </div>
  );
}
