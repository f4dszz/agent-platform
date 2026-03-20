import { useState, useEffect } from "react";
import type { Room } from "./types";
import { listRooms, createRoom, deleteRoom, listAgents } from "./services/api";
import { ThemeProvider, useTheme, t } from "./components/ThemeContext";
import RoomSidebar from "./components/RoomSidebar";
import ChatRoom from "./components/ChatRoom";

function AppInner() {
  const { mode } = useTheme();
  const tk = t(mode);
  const [rooms, setRooms] = useState<Room[]>([]);
  const [selectedRoomId, setSelectedRoomId] = useState<string | null>(null);
  const [agentStatuses, setAgentStatuses] = useState<
    Record<string, "idle" | "working" | "offline">
  >({});
  const [agentConfigVersion, setAgentConfigVersion] = useState(0);

  useEffect(() => {
    listRooms().then((data) => {
      setRooms(data.rooms);
      if (data.rooms.length > 0) {
        setSelectedRoomId((prev) => prev ?? data.rooms[0].id);
      }
    });
    listAgents().then((agents) => {
      const initial: Record<string, "idle" | "working" | "offline"> = {};
      for (const agent of agents) {
        initial[agent.name] = agent.enabled ? "idle" : "offline";
      }
      setAgentStatuses(initial);
    });
  }, []);

  const handleCreateRoom = async (name: string) => {
    const room = await createRoom(name);
    setRooms((prev) => [room, ...prev]);
    setSelectedRoomId(room.id);
  };

  const handleDeleteRoom = async (roomId: string) => {
    await deleteRoom(roomId);
    setRooms((prev) => {
      const next = prev.filter((room) => room.id !== roomId);
      setSelectedRoomId((current) => {
        if (current !== roomId) return current;
        return next[0]?.id ?? null;
      });
      return next;
    });
  };

  const selectedRoom = rooms.find((room) => room.id === selectedRoomId);

  return (
    <div className={`flex h-screen ${tk.bg} ${tk.text}`}>
      <RoomSidebar
        rooms={rooms}
        selectedRoomId={selectedRoomId}
        onSelectRoom={setSelectedRoomId}
        onCreateRoom={handleCreateRoom}
        onDeleteRoom={handleDeleteRoom}
        agentStatuses={agentStatuses}
        onAgentStatusPatch={(name, status) =>
          setAgentStatuses((prev) => ({ ...prev, [name]: status }))
        }
        onAgentConfigChange={() => setAgentConfigVersion((prev) => prev + 1)}
      />

      <main className="flex-1 flex flex-col">
        {selectedRoom ? (
          <ChatRoom
            key={selectedRoom.id}
            roomId={selectedRoom.id}
            roomName={selectedRoom.name}
            agentConfigVersion={agentConfigVersion}
            onAgentStatusChange={setAgentStatuses}
          />
        ) : (
          <div className={`flex-1 flex items-center justify-center ${tk.textMuted} ${tk.bg}`}>
            <div className="text-center">
              <div className="text-5xl mb-5 opacity-40">Chat</div>
              <p className={`text-lg font-medium ${tk.textSecondary}`}>
                Select or create a room
              </p>
              <p className={`text-sm mt-2 ${tk.textDim}`}>
                Use{" "}
                <code className={`${tk.bgTertiary} px-1.5 py-0.5 rounded text-xs text-orange-400`}>
                  @claude
                </code>{" "}
                or{" "}
                <code className={`${tk.bgTertiary} px-1.5 py-0.5 rounded text-xs text-emerald-400`}>
                  @codex
                </code>{" "}
                to talk to agents
              </p>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}

export default function App() {
  return (
    <ThemeProvider>
      <AppInner />
    </ThemeProvider>
  );
}
