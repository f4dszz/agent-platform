import { useRef, useEffect } from "react";
import type { Message } from "../types";
import { useTheme, t, bubbleClasses } from "./ThemeContext";
import MarkdownContent from "./MarkdownContent";

interface MessageListProps {
  messages: Message[];
  typingAgents: string[];
}

function senderAvatar(senderType: string): string {
  switch (senderType) {
    case "claude": return "C";
    case "codex": return "X";
    case "system": return "S";
    default: return "U";
  }
}

function avatarBg(senderType: string): string {
  switch (senderType) {
    case "claude": return "bg-gradient-to-br from-orange-500 to-amber-600";
    case "codex": return "bg-gradient-to-br from-emerald-500 to-green-600";
    case "system": return "bg-gray-600";
    default: return "bg-gradient-to-br from-blue-500 to-indigo-600";
  }
}

function senderColor(senderType: string): string {
  switch (senderType) {
    case "claude": return "text-orange-400";
    case "codex": return "text-emerald-400";
    case "system": return "text-gray-400";
    default: return "text-blue-400";
  }
}

export default function MessageList({ messages, typingAgents }: MessageListProps) {
  const { mode, bubbleStyle } = useTheme();
  const tk = t(mode);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, typingAgents]);

  if (messages.length === 0 && typingAgents.length === 0) {
    return (
      <div className={`flex-1 flex items-center justify-center ${tk.textMuted}`}>
        <div className="text-center">
          <div className="text-5xl mb-4 opacity-50">💬</div>
          <p className="text-lg">No messages yet</p>
          <p className={`text-sm mt-1 ${tk.textDim}`}>
            Type <code className={`${tk.bgTertiary} px-1.5 py-0.5 rounded text-xs`}>@claude</code> or{" "}
            <code className={`${tk.bgTertiary} px-1.5 py-0.5 rounded text-xs`}>@codex</code> to talk to an agent
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-y-auto px-4 py-3 space-y-2">
      {messages.map((msg) => {
        const isHuman = msg.sender_type === "human";
        const bubble = bubbleClasses(msg.sender_type, bubbleStyle, mode);

        return (
          <div
            key={msg.id}
            className={`flex items-start gap-3 group ${isHuman && bubbleStyle === "classic" ? "flex-row-reverse" : ""}`}
          >
            <div
              className={`w-8 h-8 rounded-lg flex items-center justify-center text-white text-xs font-bold flex-shrink-0 mt-0.5 shadow-sm ${avatarBg(msg.sender_type)}`}
            >
              {senderAvatar(msg.sender_type)}
            </div>

            <div className={`max-w-[75%] px-3.5 py-2 ${bubble}`}>
              <div className="flex items-baseline gap-2 mb-0.5">
                <span className={`font-semibold text-xs ${senderColor(msg.sender_type)}`}>
                  {msg.sender_name}
                </span>
                <span className={`text-[10px] ${tk.textDim} opacity-0 group-hover:opacity-100 transition-opacity`}>
                  {new Date(msg.created_at).toLocaleTimeString()}
                </span>
              </div>
              <MarkdownContent content={msg.content} />
            </div>
          </div>
        );
      })}

      {/* Typing indicators */}
      {typingAgents.map((agent) => {
        const isClaudeish = agent.toLowerCase().includes("claude");
        return (
          <div key={`typing-${agent}`} className="flex items-start gap-3">
            <div
              className={`w-8 h-8 rounded-lg flex items-center justify-center text-white text-xs font-bold flex-shrink-0 mt-0.5 shadow-sm ${
                isClaudeish
                  ? "bg-gradient-to-br from-orange-500 to-amber-600"
                  : "bg-gradient-to-br from-emerald-500 to-green-600"
              }`}
            >
              {isClaudeish ? "C" : "X"}
            </div>
            <div className={`${tk.bgTertiary}/40 border ${tk.borderLight} rounded-xl px-4 py-2.5`}>
              <div className={`font-semibold text-xs mb-1 ${isClaudeish ? "text-orange-400" : "text-emerald-400"}`}>
                {agent}
              </div>
              <div className="flex items-center gap-1">
                <span className="w-1.5 h-1.5 bg-gray-400 rounded-full animate-bounce [animation-delay:0ms]" />
                <span className="w-1.5 h-1.5 bg-gray-400 rounded-full animate-bounce [animation-delay:150ms]" />
                <span className="w-1.5 h-1.5 bg-gray-400 rounded-full animate-bounce [animation-delay:300ms]" />
                <span className={`text-xs ${tk.textMuted} ml-1.5`}>thinking...</span>
              </div>
            </div>
          </div>
        );
      })}

      <div ref={bottomRef} />
    </div>
  );
}
