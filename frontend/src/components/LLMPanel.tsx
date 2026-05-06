import { useState } from 'react';

interface LLMDecision {
  [phase: string]: number;
}

interface Props {
  llmDecisions?: Record<string, LLMDecision>;
  coordination?: Record<string, string>;
  time?: number;
}

export default function LLMPanel({ llmDecisions, coordination, time }: Props) {
  const [expanded, setExpanded] = useState<string | null>(null);

  if (!llmDecisions || Object.keys(llmDecisions).length === 0) {
    return (
      <div className="llm-panel">
        <h3>🤖 LLM Decisions</h3>
        <div className="llm-empty">
          {time ? 'Waiting for next LLM decision cycle...' : 'Start an LLM simulation to see decisions.'}
        </div>
      </div>
    );
  }

  const entries = Object.entries(llmDecisions);

  return (
    <div className="llm-panel">
      <h3>🤖 LLM Decisions <span className="llm-time">t={time?.toFixed(0)}s</span></h3>
      <div className="llm-grid">
        {entries.map(([iid, timings]) => {
          const nsGreen = timings[0] ?? 30;
          const ewGreen = timings[2] ?? 30;
          const isExpanded = expanded === iid;
          const coord = coordination?.[iid];

          return (
            <div
              key={iid}
              className={`llm-card ${isExpanded ? 'expanded' : ''}`}
              onClick={() => setExpanded(isExpanded ? null : iid)}
            >
              <div className="llm-card-header">
                <span className="llm-intersection-id">{iid}</span>
                <span className="llm-phase-badge">
                  NS:{nsGreen}s / EW:{ewGreen}s
                </span>
              </div>
              <div className="llm-bar-container">
                <div
                  className="llm-bar llm-bar-ns"
                  style={{ width: `${(nsGreen / (nsGreen + ewGreen)) * 100}%` }}
                  title={`NS Green: ${nsGreen}s`}
                />
                <div
                  className="llm-bar llm-bar-ew"
                  style={{ width: `${(ewGreen / (nsGreen + ewGreen)) * 100}%` }}
                  title={`EW Green: ${ewGreen}s`}
                />
              </div>
              {coord && coord !== 'no coordination needed' && (
                <div className="llm-coordination">🔗 {coord}</div>
              )}
              {isExpanded && (
                <div className="llm-details">
                  <div>Phase 0 (NS Green): {nsGreen}s</div>
                  <div>Phase 1 (NS Yellow): {timings[1] ?? 3}s</div>
                  <div>Phase 2 (EW Green): {ewGreen}s</div>
                  <div>Phase 3 (EW Yellow): {timings[3] ?? 3}s</div>
                  <div>Cycle: {nsGreen + ewGreen + 6}s</div>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
