import ReactECharts from 'echarts-for-react';
import type { QueueHistoryEntry } from '../types';

interface Props {
  history: QueueHistoryEntry[];
}

export default function QueueChart({ history }: Props) {
  const timestamps = history.map(h => new Date(h.timestamp * 1000).toLocaleTimeString());

  const option = {
    backgroundColor: 'transparent',
    title: { text: 'Queue Length Over Time', left: 'center', textStyle: { color: '#eee', fontSize: 14 } },
    tooltip: { trigger: 'axis' },
    legend: { data: ['North', 'South', 'East', 'West'], bottom: 0, textStyle: { color: '#ccc' } },
    grid: { left: 40, right: 20, top: 40, bottom: 40 },
    xAxis: { type: 'category', data: timestamps, axisLabel: { color: '#999', fontSize: 10 } },
    yAxis: { type: 'value', axisLabel: { color: '#999' }, splitLine: { lineStyle: { color: '#333' } } },
    series: [
      { name: 'North', type: 'line', data: history.map(h => h.north), smooth: true, lineStyle: { width: 2 }, itemStyle: { color: '#ff6b6b' } },
      { name: 'South', type: 'line', data: history.map(h => h.south), smooth: true, lineStyle: { width: 2 }, itemStyle: { color: '#4ecdc4' } },
      { name: 'East', type: 'line', data: history.map(h => h.east), smooth: true, lineStyle: { width: 2 }, itemStyle: { color: '#ffe66d' } },
      { name: 'West', type: 'line', data: history.map(h => h.west), smooth: true, lineStyle: { width: 2 }, itemStyle: { color: '#a29bfe' } },
    ],
  };

  return (
    <div className="queue-chart">
      <ReactECharts option={option} style={{ height: 250 }} />
    </div>
  );
}
