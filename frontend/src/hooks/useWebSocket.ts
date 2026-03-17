import { useCallback, useEffect, useRef, useState } from "react";
import type { WSIncomingMessage, WSOutgoingMessage } from "../types";

interface UseWebSocketOptions {
  roomId: string | null;
  onMessage?: (msg: WSIncomingMessage) => void;
  reconnectInterval?: number;
}

/** Detach all event handlers and close a WebSocket. */
function killSocket(ws: WebSocket) {
  ws.onopen = null;
  ws.onmessage = null;
  ws.onerror = null;
  ws.onclose = null;
  ws.close();
}

export function useWebSocket({
  roomId,
  onMessage,
  reconnectInterval = 3000,
}: UseWebSocketOptions) {
  const [connected, setConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout>>();
  const onMessageRef = useRef(onMessage);
  onMessageRef.current = onMessage;

  useEffect(() => {
    if (!roomId) return;

    let disposed = false;

    function connect() {
      if (disposed) return;

      // Kill any lingering connection
      if (wsRef.current) {
        killSocket(wsRef.current);
        wsRef.current = null;
      }

      const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
      const wsUrl = `${protocol}//${window.location.host}/ws/${roomId}`;
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      ws.onopen = () => {
        if (disposed) {
          killSocket(ws);
          return;
        }
        setConnected(true);
      };

      ws.onmessage = (event) => {
        if (disposed) return;
        try {
          const data: WSIncomingMessage = JSON.parse(event.data);
          onMessageRef.current?.(data);
        } catch {
          console.error("[WS] Failed to parse message:", event.data);
        }
      };

      ws.onclose = () => {
        if (disposed) return;
        setConnected(false);
        reconnectTimer.current = setTimeout(connect, reconnectInterval);
      };

      ws.onerror = () => ws.close();
    }

    connect();

    return () => {
      disposed = true;
      clearTimeout(reconnectTimer.current);
      if (wsRef.current) {
        killSocket(wsRef.current);
        wsRef.current = null;
      }
      setConnected(false);
    };
  }, [roomId, reconnectInterval]);

  const send = useCallback((msg: WSOutgoingMessage) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(msg));
    }
  }, []);

  return { connected, send };
}
