import ReactECharts from 'echarts-for-react';
import type { IntersectionState } from '../types';

interface Props {
  intersections: IntersectionState[];
}

export default function HeatmapOverlay({ intersections }: Props) {
  // Build heatmap data: [col, row, value]
  const data: [number, number, number][] = intersections.map((inter) => {
    const totalQueue = inter.queue_lengths.north + inter.queue_lengths.south
      + inter.queue_lengths.east + inter.queue_lengths.west;
    return [inter.col, inter.row, totalQueue];
  });

  const maxVal = Math.max(1, ...data.map(d => d[2]));

  const colLabels = ['Col 0', 'Col 1', 'Col 2'];
  const rowLabels = ['Row 0', 'Row 1'];

  const option = {
    backgroundColor: 'transparent',
    title: {
      text: 'Congestion Heatmap',
      left: 'center',
      textStyle: { color: '#eee', fontSize: 13 },
    },
    tooltip: {
      formatter: (params: { value: [number, number, number] }) => {
        const [col, row, val] = params.value;
        const id = `${row}/${col}`;
        return `Intersection ${id}<br/>Total Queue: <b>${val}</b>`;
      },
    },
    grid: { left: 60, right: 16, top: 36, bottom: 40 },
    xAxis: {
      type: 'category' as const,
      data: colLabels,
      axisLabel: { color: '#999', fontSize: 10 },
      splitArea: { show: true },
    },
    yAxis: {
      type: 'category' as const,
      data: rowLabels,
      axisLabel: { color: '#999', fontSize: 10 },
      splitArea: { show: true },
    },
    visualMap: {
      min: 0,
      max: maxVal,
      calculable: false,
      orient: 'horizontal' as const,
      left: 'center',
      bottom: 4,
      textStyle: { color: '#ccc', fontSize: 10 },
      inRange: {
        color: ['#00e676', '#c6ff00', '#ffea00', '#ff9800', '#ff1744'],
      },
    },
    series: [{
      type: 'heatmap',
      data,
      label: {
        show: true,
        formatter: (params: { value: [number, number, number] }) => {
          const [col, row] = params.value;
          const inter = intersections.find(i => i.row === row && i.col === col);
          return inter ? `${inter.id}\n${params.value[2]}` : `${params.value[2]}`;
        },
        fontSize: 11,
        color: '#fff',
      },
      emphasis: {
        itemStyle: { shadowBlur: 10, shadowColor: 'rgba(0, 0, 0, 0.5)' },
      },
    }],
  };

  return (
    <div className="heatmap-overlay">
      <ReactECharts option={option} style={{ height: 220 }} />
    </div>
  );
}
