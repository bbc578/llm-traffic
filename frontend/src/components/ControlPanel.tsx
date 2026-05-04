import { useState } from 'react';
import { startSimulation, stopSimulation } from '../api';

interface Props {
  connected: boolean;
}

export default function ControlPanel({ connected }: Props) {
  const [running, setRunning] = useState(false);
  const [llmEnabled, setLlmEnabled] = useState(false);

  const handleToggle = async () => {
    try {
      if (running) {
        await stopSimulation();
        setRunning(false);
      } else {
        await startSimulation({ llm_enabled: llmEnabled });
        setRunning(true);
      }
    } catch (e) {
      console.error('Failed to toggle simulation:', e);
    }
  };

  return (
    <div className="control-panel">
      <h3>Controls</h3>
      <div className="connection-status">
        <span className={`dot ${connected ? 'connected' : 'disconnected'}`} />
        {connected ? 'Connected' : 'Disconnected'}
      </div>
      <button className={`btn ${running ? 'btn-stop' : 'btn-start'}`} onClick={handleToggle}>
        {running ? '⏹ Stop' : '▶ Start'}
      </button>
      <div className="control-group">
        <label>LLM Control</label>
        <div className={`toggle ${llmEnabled ? 'on' : ''}`} onClick={() => setLlmEnabled(!llmEnabled)}>
          <div className="toggle-thumb" />
        </div>
      </div>
    </div>
  );
}
