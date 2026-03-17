import { useState, useEffect } from "react";
import type { Room } from "./types";
import { listRooms, createRoom } from "./services/api";
import RoomSidebar from "./components/RoomSidebar";
import ChatRoom from "./components/ChatRoom";

export default function App() {
  const [rooms, setRooms] = useState<Room[]>([]);
  const [selectedRoomId, setSelectedRoomId] = useState<string | null>(null);
  const [agentStatuses, setAgentStatuses] = useState<
    Record<string, "idle" | "working" | "offline">
  >({});

  // Load rooms on mount
  useEffect(() => {
    listRooms().then((data) => {
      setRooms(data.rooms);
      if (data.rooms.length > 0) {
        setSelectedRoomId((prev) => prev ?? data.rooms[0].id);
      }
    });
  }, []);

  const handleCreateRoom = async (name: string) => {
    const room = await createRoom(name);
    setRooms((prev) => [room, ...prev]);
    setSelectedRoomId(room.id);
  };

  const selectedRoom = rooms.find((r) => r.id === selectedRoomId);

  return (
    <div className="flex h-screen bg-gray-900 text-gray-100">
      {/* Sidebar */}
      <RoomSidebar
        rooms={rooms}
        selectedRoomId={selectedRoomId}
        onSelectRoom={setSelectedRoomId}
        onCreateRoom={handleCreateRoom}
        agentStatuses={agentStatuses}
      />

      {/* Main chat area */}
      <main className="flex-1 flex flex-col">
        {selectedRoom ? (
          <ChatRoom
            key={selectedRoom.id}
            roomId={selectedRoom.id}
            roomName={selectedRoom.name}
            onAgentStatusChange={setAgentStatuses}
          />
        ) : (
          <div className="flex-1 flex items-center justify-center text-gray-500 bg-gray-900">
            <div className="text-center">
              <div className="text-5xl mb-5 opacity-40">💬</div>
              <p className="text-lg font-medium text-gray-400">Select or create a room</p>
              <p className="text-sm mt-2 text-gray-600">
                Use{" "}
                <code className="bg-gray-800 px-1.5 py-0.5 rounded text-xs text-orange-400">@claude</code>{" "}
                or{" "}
                <code className="bg-gray-800 px-1.5 py-0.5 rounded text-xs text-emerald-400">@codex</code>{" "}
                to talk to agents
              </p>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
