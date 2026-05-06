const API_BASE = 'http://localhost:8000/api';

export interface SimulationStartConfig {
  duration?: number;
  step_length?: number;
  speed_factor?: number;
  strategy?: string;
  llm_enabled?: boolean;
  llm_interval?: number;
  green_wave?: boolean;
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

export async function runExperiment(strategies: string[], steps: number = 200): Promise<any> {
  const r = await fetch(`${API_BASE}/experiment/compare`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ strategies, steps }),
  });
  return r.json();
}

export async function getIntersections(): Promise<any> {
  const r = await fetch(`${API_BASE}/intersections`);
  return r.json();
}
