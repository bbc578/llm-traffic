import ReactECharts from 'echarts-for-react';
import type { ExperimentResult } from '../types';

interface Props {
  results: ExperimentResult[];
}

const STRATEGIES = ['LLM', 'Webster', 'Fixed', 'Random'];
const STRATEGY_COLORS: Record<string, string> = {
  LLM: '#4a9eff',
  Webster: '#00e676',
  Fixed: '#ff9800',
  Random: '#ff1744',
};

export default function ExperimentComparison({ results }: Props) {
  const metrics = ['Avg Delay', 'Throughput', 'Avg Queue'];

  const series = STRATEGIES.map((strategy) => ({
    name: strategy,
    type: 'bar' as const,
    barGap: '10%',
    itemStyle: {
      color: STRATEGY_COLORS[strategy],
      borderRadius: [4, 4, 0, 0],
    },
    data: metrics.map((metric) => {
      const r = results.find(r => r.strategy === strategy);
      if (!r) return 0;
      switch (metric) {
        case 'Avg Delay': return r.avg_delay;
        case 'Throughput': return r.throughput;
        case 'Avg Queue': return r.avg_queue;
        default: return 0;
      }
    }),
  }));

  const option = {
    backgroundColor: 'transparent',
    title: {
      text: 'Experiment Comparison',
      left: 'center',
      textStyle: { color: '#eee', fontSize: 13 },
    },
    tooltip: {
      trigger: 'axis' as const,
      axisPointer: { type: 'shadow' as const },
    },
    legend: {
      data: STRATEGIES,
      bottom: 0,
      textStyle: { color: '#ccc', fontSize: 11 },
    },
    grid: { left: 60, right: 16, top: 36, bottom: 36 },
    xAxis: {
      type: 'category' as const,
      data: metrics,
      axisLabel: { color: '#999', fontSize: 11 },
    },
    yAxis: {
      type: 'value' as const,
      axisLabel: { color: '#999' },
      splitLine: { lineStyle: { color: '#2a2a4a' } },
    },
    series,
  };

  return (
    <div className="experiment-comparison">
      <ReactECharts option={option} style={{ height: 260 }} />
    </div>
  );
}
