import ReactECharts from 'echarts-for-react';
import type { SignalTimingEntry } from '../types';

interface Props {
  entries: SignalTimingEntry[];
}

const INTERSECTION_IDS = ['0/0', '0/1', '0/2', '1/0', '1/1', '1/2'];

const PHASE_COLORS: Record<string, string> = {
  green_ns: '#00e676',
  green_ew: '#00bcd4',
  yellow_ns: '#ffea00',
  yellow_ew: '#ff9800',
};

export default function SignalTimingChart({ entries }: Props) {
  // Build series data: one series per phase type
  const seriesNames = ['NS Green', 'EW Green', 'NS Yellow', 'EW Yellow'];
  const phaseTypes = ['green_ns', 'green_ew', 'yellow_ns', 'yellow_ew'] as const;

  const series = phaseTypes.map((pt, idx) => ({
    name: seriesNames[idx],
    type: 'bar' as const,
    stack: 'signal',
    barWidth: 14,
    itemStyle: { color: PHASE_COLORS[pt], borderRadius: 2 },
    data: INTERSECTION_IDS.map((id) => {
      // Count how many entries of this phase type exist for this intersection
      const count = entries.filter(e => e.intersectionId === id && e.phaseType === pt).length;
      return count || 0;
    }),
  }));

  const option = {
    backgroundColor: 'transparent',
    title: {
      text: 'Signal Timing',
      left: 'center',
      textStyle: { color: '#eee', fontSize: 13 },
    },
    tooltip: {
      trigger: 'axis' as const,
      axisPointer: { type: 'shadow' as const },
    },
    legend: {
      data: seriesNames,
      bottom: 0,
      textStyle: { color: '#ccc', fontSize: 10 },
      itemWidth: 12,
      itemHeight: 10,
    },
    grid: { left: 50, right: 16, top: 36, bottom: 36 },
    xAxis: {
      type: 'category' as const,
      data: INTERSECTION_IDS,
      axisLabel: { color: '#999', fontSize: 10 },
      name: 'Intersection',
      nameTextStyle: { color: '#888', fontSize: 10 },
    },
    yAxis: {
      type: 'value' as const,
      axisLabel: { color: '#999' },
      splitLine: { lineStyle: { color: '#2a2a4a' } },
      name: 'Phase Count',
      nameTextStyle: { color: '#888', fontSize: 10 },
    },
    series,
  };

  return (
    <div className="signal-timing-chart">
      <ReactECharts option={option} style={{ height: 240 }} />
    </div>
  );
}
