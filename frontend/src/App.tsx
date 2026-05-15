import { useState, useCallback } from 'react';
import { useSimulationSocket } from './hooks/useSimulationSocket';
import GridCanvas from './components/GridCanvas';
import SignalTimingChart from './components/SignalTimingChart';
import HeatmapOverlay from './components/HeatmapOverlay';
import ExperimentComparison from './components/ExperimentComparison';
import LLMPanel from './components/LLMPanel';
import { startSimulation, stopSimulation, runExperiment } from './api';
import type {
  IntersectionState,
  SignalTimingEntry,
  ExperimentResult,
} from './types';
import './App.css';

const MAX_TIMING_HISTORY = 200;

type Strategy = 'LLM' | 'Webster' | 'Fixed' | 'Random' | 'MaxPressure' | 'RL';

/** Convert backend snapshot to IntersectionState[] */
function toIntersections(data: any, intersectionIds: string[]): IntersectionState[] {
  const ql = data.queue_lengths || {};
  const vc = data.vehicle_counts || {};
  const signals = data.signals || [];

  // Auto-layout: try to arrange in a grid
  const count = intersectionIds.length;
  const cols = Math.ceil(Math.sqrt(count));

  return intersectionIds.map((id, idx) => {
    const row = Math.floor(idx / cols);
    const col = idx % cols;
    const q = ql[id] || { north: 0, south: 0, east: 0, west: 0 };
    const v = vc[id] || { north: 0, south: 0, east: 0, west: 0 };

    // Determine phase from signal state
    const sig = signals.find((s: any) => s.intersection === id);
    const stateStr = sig?.state || 'GGrrGGrr';
    const ewGreen = (stateStr.slice(0, Math.ceil(stateStr.length / 2)).match(/[Gg]/g) || []).length;
    const nsGreen = (stateStr.slice(Math.ceil(stateStr.length / 2)).match(/[Gg]/g) || []).length;
    const current_phase = ewGreen > nsGreen ? 0 : 1;

    const totalQ = (q.north || 0) + (q.south || 0) + (q.east || 0) + (q.west || 0);
    const congestion_level = Math.min(1, totalQ / 30);

    return {
      id,
      row,
      col,
      current_phase,
      current_phase_duration: 30,
      queue_lengths: q,
      vehicle_counts: v,
      avg_speeds: { north: 0, south: 0, east: 0, west: 0 },
      waiting_times: { north: 0, south: 0, east: 0, west: 0 },
      congestion_level,
    };
  });
}

/** Derive signal timing entries from real signal states */
function deriveTimingEntries(data: any, prev: SignalTimingEntry[]): SignalTimingEntry[] {
  const signals = data.signals || [];
  const phaseTypes: SignalTimingEntry['phaseType'][] = ['green_ew', 'green_ns'];
  const newEntries: SignalTimingEntry[] = [];

  for (const sig of signals) {
    const stateStr = sig.state || 'GGrrGGrr';
    const halfLen = Math.ceil(stateStr.length / 2);
    const ewGreen = (stateStr.slice(0, halfLen).match(/[Gg]/g) || []).length;
    const nsGreen = (stateStr.slice(halfLen).match(/[Gg]/g) || []).length;
    const phase = ewGreen > nsGreen ? 0 : 1;

    newEntries.push({
      time: data.time,
      intersectionId: sig.intersection,
      phase,
      phaseType: phaseTypes[phase],
    });
  }

  const combined = [...prev, ...newEntries];
  return combined.length > MAX_TIMING_HISTORY ? combined.slice(-MAX_TIMING_HISTORY) : combined;
}

export default function App() {
  const [simData, setSimData] = useState<any>(null);
  const [timingEntries, setTimingEntries] = useState<SignalTimingEntry[]>([]);
  const [strategy, setStrategy] = useState<Strategy>('Fixed');
  const [running, setRunning] = useState(false);
  const [experimentResults, setExperimentResults] = useState<ExperimentResult[]>([]);
  const [experimentLoading, setExperimentLoading] = useState(false);
  const [intersectionIds, setIntersectionIds] = useState<string[]>([]);

  const handleData = useCallback((data: any) => {
    setSimData(data);
    // Update intersection list from started event
    if (data.intersections && Array.isArray(data.intersections)) {
      setIntersectionIds(data.intersections);
    }
    if (data.is_running) {
      setTimingEntries(prev => deriveTimingEntries(data, prev));
      setRunning(true);
    } else if (data.event === 'ended' || data.message === 'Simulation ended') {
      setRunning(false);
    }
  }, []);

  const { connected, status } = useSimulationSocket(handleData);

  // Use discovered intersections or fall back to snapshot keys
  const currentIds = intersectionIds.length > 0
    ? intersectionIds
    : (simData?.queue_lengths ? Object.keys(simData.queue_lengths) : []);

  const intersections = simData && currentIds.length > 0
    ? toIntersections(simData, currentIds)
    : [];

  const handleStart = async () => {
    try {
      await startSimulation({
        duration: 3600,
        speed_factor: 5,
        strategy: strategy.toLowerCase(),
        llm_enabled: strategy === 'LLM',
      });
      setRunning(true);
      setTimingEntries([]);
    } catch (e) {
      console.error('Failed to start:', e);
    }
  };

  const handleStop = async () => {
    try {
      await stopSimulation();
      setRunning(false);
    } catch (e) {
      console.error('Failed to stop:', e);
    }
  };

  const handleReset = () => {
    setSimData(null);
    setTimingEntries([]);
    setRunning(false);
    setIntersectionIds([]);
  };

  const handleRunExperiment = async () => {
    setExperimentLoading(true);
    try {
      const result = await runExperiment(['fixed', 'random', 'webster', 'maxpressure', 'rl', 'llm'], 3600);
      if (result.results) {
        const mapped: ExperimentResult[] = Object.entries(result.results).map(([strategy, metrics]: [string, any]) => ({
          strategy: strategy.charAt(0).toUpperCase() + strategy.slice(1),
          avg_wait_time: metrics.avg_wait_time || 0,
          avg_queue_length: metrics.avg_queue_length || 0,
          throughput: metrics.throughput || 0,
          vehicles_arrived: metrics.vehicles_arrived || 0,
          avg_delay: metrics.avg_delay || 0,
          avg_stops: metrics.avg_stops || 0,
        }));
        setExperimentResults(mapped);
      }
    } catch (e) {
      console.error('Experiment failed:', e);
    } finally {
      setExperimentLoading(false);
    }
  };

  return (
    <div className="app">
      <header className="app-header">
        <h1>🚦 LLM Traffic Signal Optimization</h1>
        <div className="header-status">
          <span className={`dot ${status === 'connected' ? 'connected' : status === 'reconnecting' ? 'reconnecting' : 'disconnected'}`} />
          <span className="status-text">{status === 'connected' ? 'Connected' : status === 'reconnecting' ? 'Reconnecting…' : 'Disconnected'}</span>
          {intersections.length > 0 && (
            <span className="intersection-count">{intersections.length} intersections</span>
          )}
        </div>
      </header>

      <main className="app-main">
        <div className="grid-panel">
          <GridCanvas intersections={intersections} time={simData?.time ?? 0} />
        </div>

        <div className="sidebar">
          <div className="sidebar-card">
            <SignalTimingChart entries={timingEntries} />
          </div>
          <div className="sidebar-card">
            <HeatmapOverlay intersections={intersections} />
          </div>
          <div className="sidebar-card">
            <LLMPanel
              llmDecisions={simData?.llm_decisions}
              coordination={simData?.coordination}
              time={simData?.time}
            />
          </div>
        </div>

        <div className="bottom-panel">
          <div className="controls-card">
            <h3>Controls</h3>
            <div className="control-row">
              <label>Strategy:</label>
              <select
                value={strategy}
                onChange={(e) => setStrategy(e.target.value as Strategy)}
                className="strategy-select"
                disabled={running}
              >
                <option value="LLM">LLM</option>
                <option value="Webster">Webster</option>
                <option value="Fixed">Fixed</option>
                <option value="Random">Random</option>
                <option value="MaxPressure">MaxPressure</option>
                <option value="RL">RL</option>
              </select>
            </div>
            <div className="button-row">
              <button
                className={`btn ${running ? 'btn-stop' : 'btn-start'}`}
                onClick={running ? handleStop : handleStart}
              >
                {running ? '⏹ Stop' : '▶ Start'}
              </button>
              <button className="btn btn-reset" onClick={handleReset} disabled={running}>
                🔄 Reset
              </button>
              <button
                className="btn btn-experiment"
                onClick={handleRunExperiment}
                disabled={running || experimentLoading}
              >
                {experimentLoading ? '⏳ Running...' : '📊 Run Experiment'}
              </button>
            </div>
            {simData && (
              <div className="sim-info">
                <span>Time: {(simData.time ?? 0).toFixed(1)}s</span>
                <span>Vehicles: {simData.total_vehicles ?? 0}</span>
                <span>Strategy: {simData.strategy ?? '-'}</span>
              </div>
            )}
          </div>
          <div className="experiment-card">
            <ExperimentComparison results={experimentResults} />
          </div>
        </div>
      </main>
    </div>
  );
}
