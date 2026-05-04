import { useEffect, useRef, useCallback, useState } from 'react';
import type { SimulationData } from '../types';

export function useSimulationSocket(onData: (data: SimulationData) => void) {
  const wsRef = useRef<WebSocket | null>(null);
  const [connected, setConnected] = useState(false);

  const connect = useCallback(() => {
    const ws = new WebSocket('ws://localhost:8000/ws/simulation');

    ws.onopen = () => setConnected(true);
    ws.onclose = () => {
      setConnected(false);
      setTimeout(connect, 2000);
    };
    ws.onerror = () => ws.close();
    ws.onmessage = (event) => {
      try {
        const data: SimulationData = JSON.parse(event.data);
        onData(data);
      } catch {}
    };

    wsRef.current = ws;
  }, [onData]);

  useEffect(() => {
    connect();
    return () => wsRef.current?.close();
  }, [connect]);

  return connected;
}
