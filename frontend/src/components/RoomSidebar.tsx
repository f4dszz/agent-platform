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
    <aside className="w-64 bg-gray-900 border-r border-gray-700 flex flex-col h-full">
      {/* Header */}
      <div className="p-4 border-b border-gray-700">
        <h1 className="text-lg font-bold text-white">Agent Platform</h1>
        <p className="text-xs text-gray-500">Multi-agent chat</p>
      </div>

      {/* Room list */}
      <div className="flex-1 overflow-y-auto">
        <div className="p-3">
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs font-semibold text-gray-400 uppercase tracking-wider">
              Rooms
            </span>
            <button
              onClick={() => setShowCreate(!showCreate)}
              className="text-gray-400 hover:text-white text-lg leading-none"
              title="Create room"
            >
              +
            </button>
          </div>

          {/* Create room form */}
          {showCreate && (
            <div className="mb-2 flex gap-1">
              <input
                type="text"
                value={newRoomName}
                onChange={(e) => setNewRoomName(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && handleCreate()}
                placeholder="Room name"
                className="flex-1 bg-gray-800 text-gray-200 rounded px-2 py-1 text-sm outline-none focus:ring-1 focus:ring-blue-500"
                autoFocus
              />
              <button
                onClick={handleCreate}
                className="bg-blue-600 text-white rounded px-2 py-1 text-xs"
              >
                Add
              </button>
            </div>
          )}

          {/* Room buttons */}
          {rooms.map((room) => (
            <button
              key={room.id}
              onClick={() => onSelectRoom(room.id)}
              className={`w-full text-left rounded-lg px-3 py-2 mb-1 text-sm transition-colors ${
                selectedRoomId === room.id
                  ? "bg-gray-700 text-white"
                  : "text-gray-400 hover:bg-gray-800 hover:text-gray-200"
              }`}
            >
              # {room.name}
            </button>
          ))}

          {rooms.length === 0 && (
            <p className="text-xs text-gray-600 text-center py-4">
              No rooms yet
            </p>
          )}
        </div>
      </div>

      {/* Agent statuses */}
      <div className="border-t border-gray-700">
        <div className="space-y-1 px-3 py-2">
          <div className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2">
            Agents
          </div>
          {Object.entries(agentStatuses).length === 0 ? (
            <p className="text-xs text-gray-600">No agents registered</p>
          ) : (
            Object.entries(agentStatuses).map(([name, status]) => (
              <div key={name} className="flex items-center gap-2 py-1">
                <span
                  className={`w-2 h-2 rounded-full ${
                    status === "working"
                      ? "bg-yellow-400 animate-pulse"
                      : status === "idle"
                        ? "bg-green-400"
                        : "bg-gray-500"
                  }`}
                />
                <span className="text-sm text-gray-300">{name}</span>
              </div>
            ))
          )}
        </div>
      </div>
    </aside>
  );
}
