/** Direction keys used by the backend */
export type Direction = 'north' | 'south' | 'east' | 'west';

/** Per-direction integer map */
export type DirectionIntMap = Record<Direction, number>;

/** Per-direction float map */
export type DirectionFloatMap = Record<Direction, number>;

/** Traffic light state */
export type LightState = 'red' | 'yellow' | 'green';

/** Traffic light for a single approach */
export interface TrafficLight {
  direction: Direction;
  state: LightState;
}

/** Phase history entry for signal timing chart */
export interface PhaseHistoryEntry {
  time: number;
  phase: number;
  duration: number;
}

/** State of a single intersection */
export interface IntersectionState {
  id: string;             // e.g. "0/0", "0/1", "1/0", ...
  row: number;
  col: number;
  current_phase: number;
  current_phase_duration: number;
  queue_lengths: DirectionIntMap;
  vehicle_counts: DirectionIntMap;
  avg_speeds: DirectionFloatMap;
  waiting_times: DirectionFloatMap;
  congestion_level: number; // 0-1 normalized
}

/** Multi-intersection simulation state from backend */
export interface GridSimulationData {
  time: number;
  is_running: boolean;
  total_vehicles: number;
  intersections: IntersectionState[];
  strategy: string;
  message?: string;
}

/** Experiment result for comparison chart */
export interface ExperimentResult {
  strategy: string;
  avg_wait_time: number;
  avg_queue_length: number;
  throughput: number;
  vehicles_arrived: number;
  avg_delay: number;
  avg_stops: number;
}

/** Signal timing history entry per intersection */
export interface SignalTimingEntry {
  time: number;
  intersectionId: string;
  phase: number;
  phaseType: 'green_ns' | 'green_ew' | 'yellow_ns' | 'yellow_ew';
}

/** Vehicle for canvas rendering */
export interface Vehicle {
  id: string;
  x: number;
  y: number;
  direction: Direction;
  speed: number;
  color: string;
  waiting: boolean;
}

/** LLM recommendation object from backend */
export interface LLMRecommendation {
  phase_durations: Record<number, number>;
  reasoning: string;
  raw_response: string;
}

// Legacy single-intersection types kept for backward compatibility
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
