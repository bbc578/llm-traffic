import { useState, useCallback } from 'react';
import { useSimulationSocket } from './hooks/useSimulationSocket';
import IntersectionCanvas from './components/IntersectionCanvas';
import ControlPanel from './components/ControlPanel';
import MetricsDisplay from './components/MetricsDisplay';
import QueueChart from './components/QueueChart';
import LLMPanel from './components/LLMPanel';
import type { SimulationData, QueueHistoryEntry, LLMRecommendation } from './types';
import './App.css';

const MAX_HISTORY = 60;

export default function App() {
  const [simData, setSimData] = useState<SimulationData | null>(null);
  const [queueHistory, setQueueHistory] = useState<QueueHistoryEntry[]>([]);
  const [recommendation, setRecommendation] = useState<LLMRecommendation | null>(null);

  const handleData = useCallback((data: SimulationData) => {
    setSimData(data);
    if (data.llm_recommendation) {
      setRecommendation(data.llm_recommendation);
    }
    setQueueHistory(prev => {
      const entry: QueueHistoryEntry = {
        timestamp: data.time,
        north: data.queue_lengths.north,
        south: data.queue_lengths.south,
        east: data.queue_lengths.east,
        west: data.queue_lengths.west,
      };
      const next = [...prev, entry];
      return next.length > MAX_HISTORY ? next.slice(-MAX_HISTORY) : next;
    });
  }, []);

  const connected = useSimulationSocket(handleData);

  return (
    <div className="app">
      <header className="app-header">
        <h1>🚦 LLM Traffic Control</h1>
      </header>
      <main className="app-main">
        <div className="left-panel">
          <IntersectionCanvas data={simData} />
          <LLMPanel recommendation={recommendation} />
        </div>
        <div className="right-panel">
          <ControlPanel connected={connected} />
          <MetricsDisplay data={simData} />
          <QueueChart history={queueHistory} />
        </div>
      </main>
    </div>
  );
}
