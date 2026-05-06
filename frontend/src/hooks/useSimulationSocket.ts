import { useEffect, useRef, useState } from 'react';
import type { SimulationData } from '../types';

export type ConnectionStatus = 'connected' | 'disconnected' | 'reconnecting';

const RECONNECT_BASE_MS = 1000;
const RECONNECT_MAX_MS = 10000;

export function useSimulationSocket(onData: (data: SimulationData) => void) {
  const wsRef = useRef<WebSocket | null>(null);
  const callbackRef = useRef(onData);
  const [connected, setConnected] = useState(false);
  const [status, setStatus] = useState<ConnectionStatus>('disconnected');

  // Always keep the latest callback in a ref — avoids WebSocket reconnect loop
  useEffect(() => {
    callbackRef.current = onData;
  }, [onData]);

  useEffect(() => {
    let ws: WebSocket;
    let reconnectTimer: ReturnType<typeof setTimeout>;
    let attempt = 0;
    let intentionalClose = false;

    function getBackoffMs(): number {
      // Exponential backoff: 1s, 2s, 4s, 8s, capped at 10s
      return Math.min(RECONNECT_BASE_MS * Math.pow(2, attempt), RECONNECT_MAX_MS);
    }

    function connect() {
      ws = new WebSocket('ws://localhost:8000/ws/simulation');

      ws.onopen = () => {
        attempt = 0;
        setConnected(true);
        setStatus('connected');
      };

      ws.onclose = () => {
        setConnected(false);
        if (!intentionalClose) {
          setStatus('reconnecting');
          const delay = getBackoffMs();
          attempt++;
          reconnectTimer = setTimeout(connect, delay);
        } else {
          setStatus('disconnected');
        }
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
      intentionalClose = true;
      clearTimeout(reconnectTimer);
      ws.close();
    };
  }, []);

  return { connected, status };
}
