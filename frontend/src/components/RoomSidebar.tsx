import { useState, useEffect } from "react";
import type { Room, Agent } from "../types";
import { listAgents } from "../services/api";
import { useTheme, t, type ThemeMode, type BubbleStyle } from "./ThemeContext";
import AgentSettings from "./AgentSettings";

interface RoomSidebarProps {
  rooms: Room[];
  selectedRoomId: string | null;
  onSelectRoom: (roomId: string) => void;
  onCreateRoom: (name: string) => void;
  onDeleteRoom: (roomId: string) => Promise<void>;
  agentStatuses: Record<string, "idle" | "working" | "offline">;
  onAgentStatusPatch: (name: string, status: "idle" | "working" | "offline") => void;
  onAgentConfigChange: () => void;
}

export default function RoomSidebar({
  rooms,
  selectedRoomId,
  onSelectRoom,
  onCreateRoom,
  onDeleteRoom,
  agentStatuses,
  onAgentStatusPatch,
  onAgentConfigChange,
}: RoomSidebarProps) {
  const { mode, setMode, bubbleStyle, setBubbleStyle } = useTheme();
  const tk = t(mode);
  const [newRoomName, setNewRoomName] = useState("");
  const [showCreate, setShowCreate] = useState(false);
  const [showSettings, setShowSettings] = useState(false);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [expandedAgent, setExpandedAgent] = useState<string | null>(null);

  useEffect(() => {
    listAgents().then(setAgents).catch(console.error);
  }, []);

  const handleCreate = () => {
    const name = newRoomName.trim();
    if (!name) return;
    onCreateRoom(name);
    setNewRoomName("");
    setShowCreate(false);
  };

  const themes: { key: ThemeMode; label: string }[] = [
    { key: "dark", label: "Dark" },
    { key: "light", label: "Light" },
  ];

  const bubbles: { key: BubbleStyle; label: string; desc: string }[] = [
    { key: "modern", label: "Modern", desc: "Translucent borders" },
    { key: "classic", label: "Classic", desc: "Solid colored bubbles" },
    { key: "minimal", label: "Minimal", desc: "Left-border accent" },
  ];

  return (
    <aside className={`w-60 ${tk.sidebarBg} border-r ${tk.border} flex flex-col h-full`}>
      <div className={`px-4 py-4 border-b ${tk.border}`}>
        <div className="flex items-center justify-between">
          <h1 className={`text-base font-bold ${tk.text} tracking-tight`}>Agent Platform</h1>
          <button
            onClick={() => setShowSettings(!showSettings)}
            className={`w-6 h-6 rounded-md flex items-center justify-center ${tk.textMuted} hover:${tk.text} ${tk.sidebarHover} transition-colors text-sm`}
            title="Settings"
          >
            {showSettings ? "x" : "*"}
          </button>
        </div>
        <p className={`text-[11px] ${tk.textMuted} mt-0.5`}>Multi-agent chat</p>
      </div>

      {showSettings && (
        <div className={`px-3 py-3 border-b ${tk.border} space-y-3`}>
          <div>
            <div className={`text-[10px] font-semibold ${tk.textMuted} uppercase tracking-widest mb-1.5`}>
              Theme
            </div>
            <div className="flex gap-1">
              {themes.map((themeOption) => (
                <button
                  key={themeOption.key}
                  onClick={() => setMode(themeOption.key)}
                  className={`flex-1 text-xs py-1.5 rounded-lg transition-all ${
                    mode === themeOption.key
                      ? "bg-blue-600 text-white"
                      : `${tk.bgTertiary} ${tk.textSecondary} hover:${tk.text}`
                  }`}
                >
                  {themeOption.label}
                </button>
              ))}
            </div>
          </div>

          <div>
            <div className={`text-[10px] font-semibold ${tk.textMuted} uppercase tracking-widest mb-1.5`}>
              Chat Style
            </div>
            <div className="space-y-1">
              {bubbles.map((bubble) => (
                <button
                  key={bubble.key}
                  onClick={() => setBubbleStyle(bubble.key)}
                  className={`w-full text-left text-xs px-2.5 py-1.5 rounded-lg transition-all ${
                    bubbleStyle === bubble.key
                      ? "bg-blue-600/20 text-blue-400 border border-blue-500/30"
                      : `${tk.bgTertiary} ${tk.textSecondary} border border-transparent hover:${tk.text}`
                  }`}
                >
                  <span className="font-medium">{bubble.label}</span>
                  <span className={`ml-1.5 ${tk.textDim}`}>- {bubble.desc}</span>
                </button>
              ))}
            </div>
          </div>
        </div>
      )}

      <div className="flex-1 overflow-y-auto px-2 py-2">
        <div className="flex items-center justify-between px-2 mb-1.5">
          <span className={`text-[10px] font-semibold ${tk.textMuted} uppercase tracking-widest`}>
            Rooms
          </span>
          <button
            onClick={() => setShowCreate(!showCreate)}
            className={`${tk.textMuted} hover:text-blue-400 text-base leading-none transition-colors w-5 h-5 flex items-center justify-center rounded ${tk.sidebarHover}`}
            title="Create room"
          >
            +
          </button>
        </div>

        {showCreate && (
          <div className="mx-1 mb-2 flex gap-1">
            <input
              type="text"
              value={newRoomName}
              onChange={(e) => setNewRoomName(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleCreate()}
              placeholder="room name"
              className={`flex-1 ${tk.bgTertiary} ${tk.text} rounded-lg px-2.5 py-1.5 text-xs outline-none border ${tk.border} focus:border-blue-500/50`}
              autoFocus
            />
            <button
              onClick={handleCreate}
              className="bg-blue-600 text-white rounded-lg px-2 py-1.5 text-xs hover:bg-blue-500 transition-colors"
            >
              Add
            </button>
          </div>
        )}

        {rooms.map((room) => (
          <div
            key={room.id}
            className={`group flex items-center gap-1 rounded-lg mb-0.5 border ${
              selectedRoomId === room.id
                ? tk.sidebarActive
                : `${tk.textSecondary} ${tk.sidebarHover} border-transparent`
            }`}
          >
            <button
              onClick={() => onSelectRoom(room.id)}
              className="flex-1 text-left px-3 py-2 text-sm transition-all"
            >
              <span className={tk.textDim + " mr-1"}>#</span>
              {room.name}
            </button>
            <button
              onClick={async () => {
                if (!window.confirm(`Delete room "${room.name}"?`)) return;
                await onDeleteRoom(room.id);
              }}
              className={`mr-1 hidden group-hover:flex items-center justify-center rounded-md px-2 py-1 text-[11px] ${tk.textMuted} hover:text-rose-400`}
              title="Delete room"
            >
              Del
            </button>
          </div>
        ))}

        {rooms.length === 0 && (
          <p className={`text-xs ${tk.textDim} text-center py-6`}>
            No rooms yet. Click + to create one.
          </p>
        )}
      </div>

      <div className={`border-t ${tk.border} px-3 py-3`}>
        <div className={`text-[10px] font-semibold ${tk.textMuted} uppercase tracking-widest mb-2`}>
          Agents
        </div>
        {Object.entries(agentStatuses).length === 0 ? (
          <p className={`text-xs ${tk.textDim}`}>No agents registered</p>
        ) : (
          <div className="space-y-1">
            {Object.entries(agentStatuses).map(([name, status]) => {
              const agentData = agents.find((agent) => agent.name === name);
              const isExpanded = expandedAgent === name;
              const label = agentData?.display_name ?? name;
              const avatarLabel =
                agentData?.avatar_label?.trim() || (name.includes("claude") ? "C" : "X");
              const avatarColor =
                agentData?.avatar_color?.trim() ||
                (name.includes("claude") ? "#f59e0b" : "#10b981");
              return (
                <div key={name}>
                  <button
                    onClick={() => setExpandedAgent(isExpanded ? null : name)}
                    className={`w-full flex items-center gap-2 px-1 py-1 rounded-lg transition-colors ${
                      isExpanded ? tk.sidebarActive : tk.sidebarHover
                    }`}
                    >
                      <div
                        className="w-6 h-6 rounded-md flex items-center justify-center text-white text-[10px] font-bold shrink-0"
                        style={{ backgroundColor: avatarColor }}
                      >
                        {avatarLabel}
                      </div>
                    <div className="flex-1 min-w-0 text-left">
                      <div className={`text-xs ${tk.textSecondary} truncate`}>{label}</div>
                      <div className={`text-[10px] ${tk.textDim} truncate`}>@{name}</div>
                    </div>
                    <div className="flex items-center gap-1.5">
                      <span
                        className={`w-1.5 h-1.5 rounded-full ${
                          status === "working"
                            ? "bg-yellow-400 animate-pulse shadow-[0_0_4px_rgba(250,204,21,0.5)]"
                            : status === "idle"
                              ? "bg-green-400 shadow-[0_0_4px_rgba(74,222,128,0.3)]"
                              : "bg-gray-600"
                        }`}
                      />
                      <span className={`text-[10px] ${tk.textMuted}`}>
                        {status === "working" ? "working" : status === "idle" ? "online" : "offline"}
                      </span>
                    </div>
                  </button>
                  {isExpanded && agentData && (
                    <AgentSettings
                      agent={agentData}
                      onUpdated={(updated) => {
                        setAgents((prev) =>
                          prev.map((agent) => (agent.name === updated.name ? updated : agent))
                        );
                        const nextStatus = updated.enabled
                          ? agentStatuses[updated.name] === "offline"
                            ? "idle"
                            : agentStatuses[updated.name] ?? "idle"
                          : "offline";
                        onAgentStatusPatch(updated.name, nextStatus);
                        onAgentConfigChange();
                      }}
                    />
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </aside>
  );
}
