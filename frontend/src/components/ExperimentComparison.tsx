import ReactECharts from 'echarts-for-react';
import type { ExperimentResult } from '../types';

interface Props {
  results: ExperimentResult[];
}

const STRATEGIES = ['LLM', 'RL', 'MaxPressure', 'Webster', 'Random', 'Fixed'];
const STRATEGY_COLORS: Record<string, string> = {
  LLM: '#4a9eff',
  RL: '#00e676',
  MaxPressure: '#8e44ad',
  Webster: '#ff9800',
  Random: '#ff1744',
  Fixed: '#78909c',
};

export default function ExperimentComparison({ results }: Props) {
  const metrics = [
    'Avg Wait (s)',
    'Avg Queue',
    'Throughput',
    'Vehicles Arrived',
    'Avg Delay (s)',
    'Avg Stops',
  ];

  const series = STRATEGIES.map((strategy) => ({
    name: strategy,
    type: 'bar' as const,
    barGap: '5%',
    itemStyle: {
      color: STRATEGY_COLORS[strategy],
      borderRadius: [4, 4, 0, 0],
    },
    data: metrics.map((metric) => {
      const r = results.find(r => r.strategy === strategy);
      if (!r) return 0;
      switch (metric) {
        case 'Avg Wait (s)': return r.avg_wait_time;
        case 'Avg Queue': return r.avg_queue_length;
        case 'Throughput': return r.throughput;
        case 'Vehicles Arrived': return r.vehicles_arrived;
        case 'Avg Delay (s)': return r.avg_delay;
        case 'Avg Stops': return r.avg_stops;
        default: return 0;
      }
    }),
  }));

  const option = {
    backgroundColor: 'transparent',
    title: {
      text: 'Experiment Comparison (6 Strategies)',
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
      textStyle: { color: '#ccc', fontSize: 10 },
    },
    grid: { left: 60, right: 16, top: 36, bottom: 36 },
    xAxis: {
      type: 'category' as const,
      data: metrics,
      axisLabel: { color: '#999', fontSize: 10, rotate: 15 },
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
      <ReactECharts option={option} style={{ height: 300 }} />
    </div>
  );
}
