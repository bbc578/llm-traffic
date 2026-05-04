import type { LLMRecommendation } from '../types';

interface Props {
  recommendation: LLMRecommendation | string | null;
}

export default function LLMPanel({ recommendation }: Props) {
  let content: string;

  if (!recommendation) {
    content = 'No recommendations yet. Start the simulation to see LLM analysis.';
  } else if (typeof recommendation === 'string') {
    content = recommendation;
  } else {
    const phases = Object.entries(recommendation.phase_durations)
      .map(([idx, dur]) => `Phase ${idx}: ${dur}s`)
      .join(', ');
    content = [
      `Phase durations: ${phases}`,
      '',
      recommendation.reasoning,
    ].join('\n');
  }

  return (
    <div className="llm-panel">
      <h3>🤖 LLM Recommendations</h3>
      <div className="llm-content">
        {content}
      </div>
    </div>
  );
}
