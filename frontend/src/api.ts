const API_BASE = 'http://localhost:8000/api';

export interface SimulationStartConfig {
  duration?: number;
  traffic_volumes?: Record<string, number>;
  llm_enabled?: boolean;
  llm_call_interval?: number;
  step_length?: number;
}

export async function startSimulation(config?: SimulationStartConfig): Promise<void> {
  await fetch(`${API_BASE}/simulation/start`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: config ? JSON.stringify(config) : undefined,
  });
}

export async function stopSimulation(): Promise<void> {
  await fetch(`${API_BASE}/simulation/stop`, { method: 'POST' });
}

export async function setPhase(phaseIndex: number, duration: number): Promise<void> {
  await fetch(`${API_BASE}/simulation/set-phase`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ phase_index: phaseIndex, duration }),
  });
}
