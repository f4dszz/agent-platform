import { useRef, useEffect } from "react";
import type { Message } from "../types";

interface MessageListProps {
  messages: Message[];
}

function senderIcon(senderType: string): string {
  switch (senderType) {
    case "claude":
      return "🤖";
    case "codex":
      return "⚡";
    case "system":
      return "ℹ️";
    default:
      return "👤";
  }
}

function senderColor(senderType: string): string {
  switch (senderType) {
    case "claude":
      return "text-orange-400";
    case "codex":
      return "text-green-400";
    case "system":
      return "text-gray-400";
    default:
      return "text-blue-400";
  }
}

export default function MessageList({ messages }: MessageListProps) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  if (messages.length === 0) {
    return (
      <div className="flex-1 flex items-center justify-center text-gray-500">
        <p>No messages yet. Start a conversation!</p>
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-y-auto p-4 space-y-3">
      {messages.map((msg) => (
        <div key={msg.id} className="flex items-start gap-3">
          {/* Avatar */}
          <div className="text-2xl flex-shrink-0 mt-0.5">
            {senderIcon(msg.sender_type)}
          </div>

          {/* Message body */}
          <div className="flex-1 min-w-0">
            <div className="flex items-baseline gap-2">
              <span className={`font-semibold text-sm ${senderColor(msg.sender_type)}`}>
                {msg.sender_name}
              </span>
              <span className="text-xs text-gray-500">
                {new Date(msg.created_at).toLocaleTimeString()}
              </span>
            </div>
            <div className="text-gray-200 text-sm whitespace-pre-wrap break-words mt-0.5">
              {msg.content}
            </div>
          </div>
        </div>
      ))}
      <div ref={bottomRef} />
    </div>
  );
}
