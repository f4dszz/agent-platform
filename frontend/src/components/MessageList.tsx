import { useRef, useEffect } from "react";
import type { Message } from "../types";

interface MessageListProps {
  messages: Message[];
  typingAgents: string[];
}

function senderAvatar(senderType: string): string {
  switch (senderType) {
    case "claude":
      return "C";
    case "codex":
      return "X";
    case "system":
      return "S";
    default:
      return "U";
  }
}

function avatarBg(senderType: string): string {
  switch (senderType) {
    case "claude":
      return "bg-gradient-to-br from-orange-500 to-amber-600";
    case "codex":
      return "bg-gradient-to-br from-emerald-500 to-green-600";
    case "system":
      return "bg-gray-600";
    default:
      return "bg-gradient-to-br from-blue-500 to-indigo-600";
  }
}

function messageBg(senderType: string): string {
  switch (senderType) {
    case "human":
      return "bg-blue-600/20 border border-blue-500/20";
    case "claude":
      return "bg-orange-600/10 border border-orange-500/20";
    case "codex":
      return "bg-emerald-600/10 border border-emerald-500/20";
    default:
      return "bg-gray-700/50 border border-gray-600/30";
  }
}

function senderColor(senderType: string): string {
  switch (senderType) {
    case "claude":
      return "text-orange-400";
    case "codex":
      return "text-emerald-400";
    case "system":
      return "text-gray-400";
    default:
      return "text-blue-400";
  }
}

export default function MessageList({ messages, typingAgents }: MessageListProps) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, typingAgents]);

  if (messages.length === 0 && typingAgents.length === 0) {
    return (
      <div className="flex-1 flex items-center justify-center text-gray-500">
        <div className="text-center">
          <div className="text-5xl mb-4 opacity-50">💬</div>
          <p className="text-lg">No messages yet</p>
          <p className="text-sm mt-1 text-gray-600">
            Type <code className="bg-gray-800 px-1.5 py-0.5 rounded text-xs">@claude</code> or{" "}
            <code className="bg-gray-800 px-1.5 py-0.5 rounded text-xs">@codex</code> to talk to an
            agent
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-y-auto px-4 py-3 space-y-2">
      {messages.map((msg) => (
        <div key={msg.id} className="flex items-start gap-3 group">
          {/* Avatar */}
          <div
            className={`w-8 h-8 rounded-lg flex items-center justify-center text-white text-xs font-bold flex-shrink-0 mt-0.5 shadow-sm ${avatarBg(msg.sender_type)}`}
          >
            {senderAvatar(msg.sender_type)}
          </div>

          {/* Bubble */}
          <div className={`max-w-[75%] rounded-xl px-3.5 py-2 ${messageBg(msg.sender_type)}`}>
            <div className="flex items-baseline gap-2 mb-0.5">
              <span className={`font-semibold text-xs ${senderColor(msg.sender_type)}`}>
                {msg.sender_name}
              </span>
              <span className="text-[10px] text-gray-500 opacity-0 group-hover:opacity-100 transition-opacity">
                {new Date(msg.created_at).toLocaleTimeString()}
              </span>
            </div>
            <div className="text-gray-200 text-sm whitespace-pre-wrap break-words leading-relaxed">
              {msg.content}
            </div>
          </div>
        </div>
      ))}

      {/* Typing indicators */}
      {typingAgents.map((agent) => (
        <div key={`typing-${agent}`} className="flex items-start gap-3">
          <div
            className={`w-8 h-8 rounded-lg flex items-center justify-center text-white text-xs font-bold flex-shrink-0 mt-0.5 shadow-sm ${
              agent.toLowerCase().includes("claude")
                ? "bg-gradient-to-br from-orange-500 to-amber-600"
                : "bg-gradient-to-br from-emerald-500 to-green-600"
            }`}
          >
            {agent.toLowerCase().includes("claude") ? "C" : "X"}
          </div>
          <div className="bg-gray-700/40 border border-gray-600/20 rounded-xl px-4 py-2.5">
            <div className={`font-semibold text-xs mb-1 ${
              agent.toLowerCase().includes("claude") ? "text-orange-400" : "text-emerald-400"
            }`}>
              {agent}
            </div>
            <div className="flex items-center gap-1">
              <span className="w-1.5 h-1.5 bg-gray-400 rounded-full animate-bounce [animation-delay:0ms]" />
              <span className="w-1.5 h-1.5 bg-gray-400 rounded-full animate-bounce [animation-delay:150ms]" />
              <span className="w-1.5 h-1.5 bg-gray-400 rounded-full animate-bounce [animation-delay:300ms]" />
              <span className="text-xs text-gray-500 ml-1.5">thinking...</span>
            </div>
          </div>
        </div>
      ))}

      <div ref={bottomRef} />
    </div>
  );
}
