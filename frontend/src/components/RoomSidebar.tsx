import { useState } from "react";
import type { Room } from "../types";
import { useTheme, t, type ThemeMode, type BubbleStyle } from "./ThemeContext";

interface RoomSidebarProps {
  rooms: Room[];
  selectedRoomId: string | null;
  onSelectRoom: (roomId: string) => void;
  onCreateRoom: (name: string) => void;
  agentStatuses: Record<string, "idle" | "working" | "offline">;
}

export default function RoomSidebar({
  rooms,
  selectedRoomId,
  onSelectRoom,
  onCreateRoom,
  agentStatuses,
}: RoomSidebarProps) {
  const { mode, setMode, bubbleStyle, setBubbleStyle } = useTheme();
  const tk = t(mode);
  const [newRoomName, setNewRoomName] = useState("");
  const [showCreate, setShowCreate] = useState(false);
  const [showSettings, setShowSettings] = useState(false);

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
      {/* Header */}
      <div className={`px-4 py-4 border-b ${tk.border}`}>
        <div className="flex items-center justify-between">
          <h1 className={`text-base font-bold ${tk.text} tracking-tight`}>Agent Platform</h1>
          <button
            onClick={() => setShowSettings(!showSettings)}
            className={`w-6 h-6 rounded-md flex items-center justify-center ${tk.textMuted} hover:${tk.text} ${tk.sidebarHover} transition-colors text-sm`}
            title="Settings"
          >
            {showSettings ? "×" : "⚙"}
          </button>
        </div>
        <p className={`text-[11px] ${tk.textMuted} mt-0.5`}>Multi-agent chat</p>
      </div>

      {/* Settings panel */}
      {showSettings && (
        <div className={`px-3 py-3 border-b ${tk.border} space-y-3`}>
          {/* Theme mode */}
          <div>
            <div className={`text-[10px] font-semibold ${tk.textMuted} uppercase tracking-widest mb-1.5`}>
              Theme
            </div>
            <div className="flex gap-1">
              {themes.map((th) => (
                <button
                  key={th.key}
                  onClick={() => setMode(th.key)}
                  className={`flex-1 text-xs py-1.5 rounded-lg transition-all ${
                    mode === th.key
                      ? "bg-blue-600 text-white"
                      : `${tk.bgTertiary} ${tk.textSecondary} hover:${tk.text}`
                  }`}
                >
                  {th.label}
                </button>
              ))}
            </div>
          </div>

          {/* Bubble style */}
          <div>
            <div className={`text-[10px] font-semibold ${tk.textMuted} uppercase tracking-widest mb-1.5`}>
              Chat Style
            </div>
            <div className="space-y-1">
              {bubbles.map((b) => (
                <button
                  key={b.key}
                  onClick={() => setBubbleStyle(b.key)}
                  className={`w-full text-left text-xs px-2.5 py-1.5 rounded-lg transition-all ${
                    bubbleStyle === b.key
                      ? "bg-blue-600/20 text-blue-400 border border-blue-500/30"
                      : `${tk.bgTertiary} ${tk.textSecondary} border border-transparent hover:${tk.text}`
                  }`}
                >
                  <span className="font-medium">{b.label}</span>
                  <span className={`ml-1.5 ${tk.textDim}`}>— {b.desc}</span>
                </button>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Room list */}
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
          <button
            key={room.id}
            onClick={() => onSelectRoom(room.id)}
            className={`w-full text-left rounded-lg px-3 py-2 mb-0.5 text-sm transition-all border ${
              selectedRoomId === room.id
                ? tk.sidebarActive
                : `${tk.textSecondary} ${tk.sidebarHover} border-transparent`
            }`}
          >
            <span className={tk.textDim + " mr-1"}>#</span>
            {room.name}
          </button>
        ))}

        {rooms.length === 0 && (
          <p className={`text-xs ${tk.textDim} text-center py-6`}>
            No rooms yet. Click + to create one.
          </p>
        )}
      </div>

      {/* Agent statuses */}
      <div className={`border-t ${tk.border} px-3 py-3`}>
        <div className={`text-[10px] font-semibold ${tk.textMuted} uppercase tracking-widest mb-2`}>
          Agents
        </div>
        {Object.entries(agentStatuses).length === 0 ? (
          <p className={`text-xs ${tk.textDim}`}>No agents registered</p>
        ) : (
          <div className="space-y-1.5">
            {Object.entries(agentStatuses).map(([name, status]) => (
              <div key={name} className="flex items-center gap-2">
                <div
                  className={`w-6 h-6 rounded-md flex items-center justify-center text-white text-[10px] font-bold ${
                    name.includes("claude")
                      ? "bg-gradient-to-br from-orange-500 to-amber-600"
                      : "bg-gradient-to-br from-emerald-500 to-green-600"
                  }`}
                >
                  {name.includes("claude") ? "C" : "X"}
                </div>
                <span className={`text-xs ${tk.textSecondary} flex-1`}>{name}</span>
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
              </div>
            ))}
          </div>
        )}
      </div>
    </aside>
  );
}
