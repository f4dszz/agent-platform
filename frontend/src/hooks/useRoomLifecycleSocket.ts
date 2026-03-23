import type { WSRoomLifecycleMessage } from "../types";
import { useSocket } from "./useSocket";

interface UseRoomLifecycleSocketOptions {
  onMessage?: (msg: WSRoomLifecycleMessage) => void;
  reconnectInterval?: number;
}

export function useRoomLifecycleSocket({
  onMessage,
  reconnectInterval = 3000,
}: UseRoomLifecycleSocketOptions) {
  return useSocket<WSRoomLifecycleMessage>({
    path: "/ws/lifecycle/rooms",
    onMessage,
    reconnectInterval,
  });
}
