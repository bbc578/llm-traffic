import { useEffect, useRef, useState } from 'react';
import type { SimulationData } from '../types';

export function useSimulationSocket(onData: (data: SimulationData) => void) {
  const wsRef = useRef<WebSocket | null>(null);
  const callbackRef = useRef(onData);
  const [connected, setConnected] = useState(false);

  // Always keep the latest callback in a ref — avoids WebSocket reconnect loop
  useEffect(() => {
    callbackRef.current = onData;
  }, [onData]);

  useEffect(() => {
    let ws: WebSocket;
    let reconnectTimer: ReturnType<typeof setTimeout>;

    function connect() {
      ws = new WebSocket('ws://localhost:8000/ws/simulation');

      ws.onopen = () => setConnected(true);
      ws.onclose = () => {
        setConnected(false);
        reconnectTimer = setTimeout(connect, 2000);
      };
      ws.onerror = () => ws.close();
      ws.onmessage = (event) => {
        try {
          const data: SimulationData = JSON.parse(event.data);
          callbackRef.current(data);
        } catch {}
      };

      wsRef.current = ws;
    }

    connect();

    return () => {
      clearTimeout(reconnectTimer);
      ws.close();
    };
  }, []); // Empty deps — connect once, never reconnect

  return connected;
}
