import { useCallback, useEffect, useRef, useState } from "react";
import type { WSIncomingMessage, WSOutgoingMessage } from "../types";

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
  const [connected, setConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout>>();
  // Use refs to hold latest callbacks without triggering reconnects
  const onMessageRef = useRef(onMessage);
  onMessageRef.current = onMessage;

  useEffect(() => {
    if (!roomId) return;

    let disposed = false;

    function connect() {
      if (disposed) return;

      // Close any existing connection first
      if (wsRef.current) {
        wsRef.current.onclose = null; // prevent reconnect on intentional close
        wsRef.current.close();
        wsRef.current = null;
      }

      const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
      const wsUrl = `${protocol}//${window.location.host}/ws/${roomId}`;

      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      ws.onopen = () => {
        if (disposed) {
          ws.close();
          return;
        }
        setConnected(true);
        console.log(`[WS] Connected to room ${roomId}`);
      };

      ws.onmessage = (event) => {
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
        console.log("[WS] Disconnected, reconnecting...");
        reconnectTimer.current = setTimeout(connect, reconnectInterval);
      };

      ws.onerror = (err) => {
        console.error("[WS] Error:", err);
        ws.close();
      };
    }

    connect();

    return () => {
      disposed = true;
      clearTimeout(reconnectTimer.current);
      if (wsRef.current) {
        wsRef.current.onclose = null;
        wsRef.current.close();
        wsRef.current = null;
      }
      setConnected(false);
    };
  }, [roomId, reconnectInterval]);

  const send = useCallback((msg: WSOutgoingMessage) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(msg));
    } else {
      console.warn("[WS] Cannot send — not connected");
    }
  }, []);

  return { connected, send };
}
