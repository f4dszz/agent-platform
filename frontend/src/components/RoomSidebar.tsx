import { useState } from "react";
import type { Room } from "../types";

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
  const [newRoomName, setNewRoomName] = useState("");
  const [showCreate, setShowCreate] = useState(false);

  const handleCreate = () => {
    const name = newRoomName.trim();
    if (!name) return;
    onCreateRoom(name);
    setNewRoomName("");
    setShowCreate(false);
  };

  return (
    <aside className="w-60 bg-gray-900 border-r border-gray-800 flex flex-col h-full">
      {/* Header */}
      <div className="px-4 py-4 border-b border-gray-800">
        <h1 className="text-base font-bold text-white tracking-tight">Agent Platform</h1>
        <p className="text-[11px] text-gray-500 mt-0.5">Multi-agent chat</p>
      </div>

      {/* Room list */}
      <div className="flex-1 overflow-y-auto px-2 py-2">
        <div className="flex items-center justify-between px-2 mb-1.5">
          <span className="text-[10px] font-semibold text-gray-500 uppercase tracking-widest">
            Rooms
          </span>
          <button
            onClick={() => setShowCreate(!showCreate)}
            className="text-gray-500 hover:text-blue-400 text-base leading-none transition-colors w-5 h-5 flex items-center justify-center rounded hover:bg-gray-800"
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
              className="flex-1 bg-gray-800 text-gray-200 rounded-lg px-2.5 py-1.5 text-xs outline-none border border-gray-700 focus:border-blue-500/50"
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
            className={`w-full text-left rounded-lg px-3 py-2 mb-0.5 text-sm transition-all ${
              selectedRoomId === room.id
                ? "bg-blue-600/20 text-blue-300 border border-blue-500/20"
                : "text-gray-400 hover:bg-gray-800/70 hover:text-gray-200 border border-transparent"
            }`}
          >
            <span className="text-gray-600 mr-1">#</span>
            {room.name}
          </button>
        ))}

        {rooms.length === 0 && (
          <p className="text-xs text-gray-600 text-center py-6">
            No rooms yet. Click + to create one.
          </p>
        )}
      </div>

      {/* Agent statuses */}
      <div className="border-t border-gray-800 px-3 py-3">
        <div className="text-[10px] font-semibold text-gray-500 uppercase tracking-widest mb-2">
          Agents
        </div>
        {Object.entries(agentStatuses).length === 0 ? (
          <p className="text-xs text-gray-600">No agents registered</p>
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
                <span className="text-xs text-gray-300 flex-1">{name}</span>
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
                  <span className="text-[10px] text-gray-500">
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
