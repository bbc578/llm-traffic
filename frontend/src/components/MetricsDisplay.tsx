import type { SimulationData } from '../types';

interface Props {
  data: SimulationData | null;
}

export default function MetricsDisplay({ data }: Props) {
  const m = data;

  const avgSpeed = m ? Object.values(m.avg_speeds).reduce((a, b) => a + b, 0) / 4 : 0;
  const avgWait = m ? Object.values(m.waiting_times).reduce((a, b) => a + b, 0) / 4 : 0;

  return (
    <div className="metrics-display">
      <h3>Metrics</h3>
      <div className="metrics-grid">
        <div className="metric-card">
          <span className="metric-value">{m?.total_vehicles ?? 0}</span>
          <span className="metric-label">Vehicles</span>
        </div>
        <div className="metric-card">
          <span className="metric-value">{avgSpeed.toFixed(1)}</span>
          <span className="metric-label">Avg Speed (m/s)</span>
        </div>
        <div className="metric-card">
          <span className="metric-value">{avgWait.toFixed(1)}s</span>
          <span className="metric-label">Avg Wait</span>
        </div>
      </div>
      <div className="queue-lengths">
        <h4>Queue Lengths</h4>
        <div className="queue-grid">
          <div className="queue-item north">
            <span className="dir">N</span>
            <span className="val">{m?.queue_lengths?.north ?? 0}</span>
          </div>
          <div className="queue-item south">
            <span className="dir">S</span>
            <span className="val">{m?.queue_lengths?.south ?? 0}</span>
          </div>
          <div className="queue-item east">
            <span className="dir">E</span>
            <span className="val">{m?.queue_lengths?.east ?? 0}</span>
          </div>
          <div className="queue-item west">
            <span className="dir">W</span>
            <span className="val">{m?.queue_lengths?.west ?? 0}</span>
          </div>
        </div>
      </div>
    </div>
  );
}
