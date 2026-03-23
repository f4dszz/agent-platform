import { useCallback, useEffect, useState } from "react";
import type { Room, WSRoomLifecycleMessage } from "./types";
import { listRooms, createRoom, deleteRoom, listAgents } from "./services/api";
import { ThemeProvider, useTheme, t } from "./components/ThemeContext";
import RoomSidebar from "./components/RoomSidebar";
import ChatRoom from "./components/ChatRoom";
import { useRoomLifecycleSocket } from "./hooks/useRoomLifecycleSocket";

function sortRooms(rooms: Room[]): Room[] {
  return [...rooms].sort(
    (left, right) =>
      new Date(right.created_at).getTime() - new Date(left.created_at).getTime()
  );
}

function upsertRoom(rooms: Room[], nextRoom: Room): Room[] {
  const existingIndex = rooms.findIndex((room) => room.id === nextRoom.id);
  if (existingIndex >= 0) {
    const updated = [...rooms];
    updated[existingIndex] = { ...updated[existingIndex], ...nextRoom };
    return updated;
  }
  return [nextRoom, ...rooms];
}

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
      setRooms(sortRooms(data.rooms));
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

  const handleRoomLifecycleMessage = useCallback((msg: WSRoomLifecycleMessage) => {
    switch (msg.type) {
      case "room_created":
        setRooms((prev) => sortRooms(upsertRoom(prev, msg)));
        setSelectedRoomId((current) => current ?? msg.id);
        break;
      case "room_deleted":
        setRooms((prev) => {
          const next = prev.filter((room) => room.id !== msg.room_id);
          setSelectedRoomId((current) => {
            if (current !== msg.room_id) return current;
            return next[0]?.id ?? null;
          });
          return next;
        });
        break;
      case "error":
        console.error("[Rooms] Lifecycle socket error:", msg.content);
        break;
    }
  }, []);

  useRoomLifecycleSocket({ onMessage: handleRoomLifecycleMessage });

  const handleCreateRoom = async (name: string) => {
    const room = await createRoom(name);
    setRooms((prev) => sortRooms(upsertRoom(prev, room)));
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

  const refreshRooms = useCallback(async () => {
    const data = await listRooms();
    setRooms(sortRooms(data.rooms));
    setSelectedRoomId((current) => {
      if (current && data.rooms.some((r) => r.id === current)) return current;
      return data.rooms[0]?.id ?? null;
    });
  }, []);

  const selectedRoom = rooms.find((room) => room.id === selectedRoomId);

  return (
    <div className={`flex h-screen ${tk.bg} ${tk.text}`}>
      <RoomSidebar
        rooms={rooms}
        selectedRoomId={selectedRoomId}
        onSelectRoom={setSelectedRoomId}
        onCreateRoom={handleCreateRoom}
        onDeleteRoom={handleDeleteRoom}
        onRoomsChanged={refreshRooms}
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
