import { useRef, useEffect, useState } from "react";
import type { Agent, AgentArtifact, Message } from "../types";
import { useTheme, t, bubbleClasses } from "./ThemeContext";
import MarkdownContent from "./MarkdownContent";

interface MessageListProps {
  messages: Message[];
  typingAgents: string[];
  artifactsByMessage: Record<string, AgentArtifact[]>;
  agents: Agent[];
}

const MAX_COLLAPSED_LINES = 24;
const MAX_COLLAPSED_CHARS = 1800;
const MAX_ARTIFACT_PREVIEW_CHARS = 180;

function senderAvatar(senderType: string): string {
  switch (senderType) {
    case "claude": return "C";
    case "codex": return "X";
    case "system": return "S";
    default: return "U";
  }
}

function defaultAvatarColor(senderType: string): string {
  switch (senderType) {
    case "claude": return "#f59e0b";
    case "codex": return "#10b981";
    case "system": return "#4b5563";
    default: return "#2563eb";
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

function resolveAgentVisual(
  senderType: string,
  senderName: string,
  agents: Agent[]
): { label: string; color: string } {
  const matchedAgent = agents.find(
    (agent) => agent.display_name === senderName || agent.name === senderName
  );
  return {
    label: matchedAgent?.avatar_label?.trim() || senderAvatar(senderType),
    color: matchedAgent?.avatar_color?.trim() || defaultAvatarColor(senderType),
  };
}

function artifactTone(
  artifact: AgentArtifact,
  dark: boolean
): { frame: string; badge: string; status: string } {
  switch (artifact.artifact_type) {
    case "plan":
      return dark
        ? {
            frame: "border-sky-500/20 bg-sky-500/10",
            badge: "bg-sky-500/20 text-sky-200",
            status: "bg-sky-950/80 text-sky-200",
          }
        : {
            frame: "border-sky-200 bg-sky-50",
            badge: "bg-sky-100 text-sky-700",
            status: "bg-white text-sky-700",
          };
    case "review":
      return dark
        ? {
            frame: "border-amber-500/20 bg-amber-500/10",
            badge: "bg-amber-500/20 text-amber-200",
            status: "bg-amber-950/70 text-amber-200",
          }
        : {
            frame: "border-amber-200 bg-amber-50",
            badge: "bg-amber-100 text-amber-700",
            status: "bg-white text-amber-700",
          };
    case "decision":
      return dark
        ? {
            frame: "border-emerald-500/20 bg-emerald-500/10",
            badge: "bg-emerald-500/20 text-emerald-200",
            status: "bg-emerald-950/70 text-emerald-200",
          }
        : {
            frame: "border-emerald-200 bg-emerald-50",
            badge: "bg-emerald-100 text-emerald-700",
            status: "bg-white text-emerald-700",
          };
    default:
      return dark
        ? {
            frame: "border-gray-700 bg-gray-800/60",
            badge: "bg-gray-700 text-gray-200",
            status: "bg-gray-950/70 text-gray-200",
          }
        : {
            frame: "border-gray-200 bg-gray-100",
            badge: "bg-white text-gray-700",
            status: "bg-white text-gray-700",
          };
  }
}

function formatArtifactLabel(value: string): string {
  return value
    .split("_")
    .filter(Boolean)
    .map((part) => part[0].toUpperCase() + part.slice(1))
    .join(" ");
}

function ArtifactCard({ artifact }: { artifact: AgentArtifact }) {
  const { mode } = useTheme();
  const tk = t(mode);
  const dark = mode === "dark";
  const tone = artifactTone(artifact, dark);
  const preview = artifact.content.replace(/\s+/g, " ").trim();
  const compactPreview =
    preview.length > MAX_ARTIFACT_PREVIEW_CHARS
      ? `${preview.slice(0, MAX_ARTIFACT_PREVIEW_CHARS - 3).trimEnd()}...`
      : preview;

  return (
    <div className={`mb-2 rounded-xl border px-3 py-2 ${tone.frame}`}>
      <div className="flex flex-wrap items-center gap-2">
        <span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold uppercase tracking-[0.16em] ${tone.badge}`}>
          {formatArtifactLabel(artifact.artifact_type)}
        </span>
        <span className={`text-[11px] font-medium ${tk.textSecondary}`}>{artifact.agent_name}</span>
        {artifact.status ? (
          <span className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${tone.status}`}>
            {formatArtifactLabel(artifact.status)}
          </span>
        ) : null}
      </div>
      {artifact.title ? (
        <div className={`mt-2 text-sm font-medium ${tk.text}`}>{artifact.title}</div>
      ) : null}
      {compactPreview && compactPreview !== artifact.title ? (
        <div className={`mt-1 text-xs leading-6 ${tk.textSecondary}`}>{compactPreview}</div>
      ) : null}
    </div>
  );
}

export default function MessageList({
  messages,
  typingAgents,
  artifactsByMessage,
  agents,
}: MessageListProps) {
  const { mode, bubbleStyle } = useTheme();
  const tk = t(mode);
  const bottomRef = useRef<HTMLDivElement>(null);
  const [expandedMessages, setExpandedMessages] = useState<Record<string, boolean>>({});

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
        const artifacts = artifactsByMessage[msg.id] ?? [];
        const lineCount = msg.content.split("\n").length;
        const shouldCollapse =
          !msg.streaming &&
          (lineCount > MAX_COLLAPSED_LINES || msg.content.length > MAX_COLLAPSED_CHARS);
        const expanded = expandedMessages[msg.id] ?? false;
        const avatar = resolveAgentVisual(msg.sender_type, msg.sender_name, agents);

        return (
          <div
            id={`message-${msg.id}`}
            key={msg.id}
            className={`flex items-start gap-3 group ${isHuman && bubbleStyle === "classic" ? "flex-row-reverse" : ""}`}
          >
            <div
              className="w-8 h-8 rounded-lg flex items-center justify-center text-white text-xs font-bold flex-shrink-0 mt-0.5 shadow-sm"
              style={{ backgroundColor: avatar.color }}
            >
              {avatar.label}
            </div>

            <div className={`max-w-[75%] px-3.5 py-2 ${bubble}`}>
              {artifacts.map((artifact) => (
                <ArtifactCard key={artifact.id} artifact={artifact} />
              ))}
              <div className="flex items-baseline gap-2 mb-0.5">
                <span className={`font-semibold text-xs ${senderColor(msg.sender_type)}`}>
                  {msg.sender_name}
                </span>
                <span className={`text-[10px] ${tk.textDim} opacity-0 group-hover:opacity-100 transition-opacity`}>
                  {new Date(msg.created_at).toLocaleTimeString()}
                </span>
                {msg.streaming ? (
                  <span className={`text-[10px] ${tk.textMuted} animate-pulse`}>
                    streaming...
                  </span>
                ) : null}
              </div>
              <div className={shouldCollapse && !expanded ? "relative" : ""}>
                <div
                  className={
                    shouldCollapse && !expanded
                      ? "max-h-[28rem] overflow-hidden"
                      : ""
                  }
                >
                  <MarkdownContent content={msg.content} />
                </div>
                {shouldCollapse && !expanded ? (
                  <div
                    className={`pointer-events-none absolute inset-x-0 bottom-0 h-24 ${
                      mode === "dark"
                        ? "bg-gradient-to-b from-transparent to-gray-900/95"
                        : "bg-gradient-to-b from-transparent to-white/95"
                    }`}
                  />
                ) : null}
              </div>
              {shouldCollapse ? (
                <button
                  type="button"
                  onClick={() =>
                    setExpandedMessages((prev) => ({
                      ...prev,
                      [msg.id]: !expanded,
                    }))
                  }
                  className={`mt-2 text-xs font-medium ${
                    mode === "dark"
                      ? "text-sky-300 hover:text-sky-200"
                      : "text-sky-700 hover:text-sky-600"
                  }`}
                >
                  {expanded ? "Collapse" : "Expand long output"}
                </button>
              ) : null}
            </div>
          </div>
        );
      })}

      {/* Typing indicators */}
      {typingAgents.map((agent) => {
        const isClaudeish = agent.toLowerCase().includes("claude");
        const avatar = resolveAgentVisual(
          isClaudeish ? "claude" : "codex",
          agent,
          agents
        );
        return (
          <div key={`typing-${agent}`} className="flex items-start gap-3">
            <div
              className="w-8 h-8 rounded-lg flex items-center justify-center text-white text-xs font-bold flex-shrink-0 mt-0.5 shadow-sm"
              style={{ backgroundColor: avatar.color }}
            >
              {avatar.label}
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
