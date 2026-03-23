import type { WSIncomingMessage, WSOutgoingMessage } from "../types";
import { useSocket } from "./useSocket";

interface UseWebSocketOptions {
  roomId: string | null;
  onMessage?: (msg: WSIncomingMessage) => void;
  reconnectInterval?: number;
}

export function useWebSocket({
  roomId,
  onMessage,
  reconnectInterval = 3000,
}: UseWebSocketOptions) {
  return useSocket<WSIncomingMessage, WSOutgoingMessage>({
    path: roomId ? `/ws/${roomId}` : null,
    onMessage,
    reconnectInterval,
  });
}
