import { useCallback, useEffect, useRef, useState } from "react";

interface UseSocketOptions<TIncoming> {
  path: string | null;
  onMessage?: (msg: TIncoming) => void;
  reconnectInterval?: number;
}

function killSocket(ws: WebSocket) {
  ws.onopen = null;
  ws.onmessage = null;
  ws.onerror = null;
  ws.onclose = null;
  ws.close();
}

export function useSocket<TIncoming, TOutgoing = unknown>({
  path,
  onMessage,
  reconnectInterval = 3000,
}: UseSocketOptions<TIncoming>) {
  const [connected, setConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout>>(undefined);
  const onMessageRef = useRef(onMessage);
  onMessageRef.current = onMessage;

  useEffect(() => {
    if (!path) return;

    let disposed = false;

    function connect() {
      if (disposed) return;

      if (wsRef.current) {
        killSocket(wsRef.current);
        wsRef.current = null;
      }

      const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
      const ws = new WebSocket(`${protocol}//${window.location.host}${path}`);
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
          const data: TIncoming = JSON.parse(event.data);
          onMessageRef.current?.(data);
        } catch {
          console.error("[WS] Failed to parse message:", event.data);
        }
      };

      ws.onclose = (event) => {
        if (disposed) return;
        setConnected(false);
        if (event.code === 4404) return;
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
  }, [path, reconnectInterval]);

  const send = useCallback((msg: TOutgoing) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(msg));
    }
  }, []);

  return { connected, send };
}
