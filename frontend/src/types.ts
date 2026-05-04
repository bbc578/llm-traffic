/** Direction keys used by the backend */
export type Direction = 'north' | 'south' | 'east' | 'west';

/** Per-direction integer map */
export type DirectionIntMap = Record<Direction, number>;

/** Per-direction float map */
export type DirectionFloatMap = Record<Direction, number>;

/** Vehicle for canvas rendering (synthetic, derived from queue data) */
export interface Vehicle {
  id: string;
  x: number;
  y: number;
  direction: Direction;
  speed: number;
  color: string;
  waiting: boolean;
}

/** Traffic light for canvas rendering (derived from current_phase) */
export interface TrafficLight {
  direction: Direction;
  state: 'red' | 'yellow' | 'green';
}

/** LLM recommendation object from backend */
export interface LLMRecommendation {
  phase_durations: Record<number, number>;
  reasoning: string;
  raw_response: string;
}

/**
 * Simulation state as sent by the backend via WebSocket.
 * Matches the dict returned by SumoEngine.get_traffic_state().
 */
export interface SimulationData {
  time: number;
  is_running: boolean;
  total_vehicles: number;
  vehicle_counts: DirectionIntMap;
  queue_lengths: DirectionIntMap;
  avg_speeds: DirectionFloatMap;
  waiting_times: DirectionFloatMap;
  current_phase: number;
  current_phase_duration: number;
  llm_recommendation?: LLMRecommendation;
  message?: string;
}

export interface QueueHistoryEntry {
  timestamp: number;
  north: number;
  south: number;
  east: number;
  west: number;
}
