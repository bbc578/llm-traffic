import { useRef, useEffect, useCallback } from 'react';
import type { SimulationData, Vehicle, TrafficLight, Direction } from '../types';

interface Props {
  data: SimulationData | null;
}

const CANVAS_SIZE = 500;
const ROAD_WIDTH = 80;
const CENTER = CANVAS_SIZE / 2;

/** Derive traffic light states from the current phase index. */
function deriveTrafficLights(phase: number): TrafficLight[] {
  // Phase 0: NS green, EW red
  // Phase 1: NS yellow, EW red
  // Phase 2: EW green, NS red
  // Phase 3: EW yellow, NS red
  let nsState: 'green' | 'yellow' | 'red';
  let ewState: 'green' | 'yellow' | 'red';

  switch (phase) {
    case 0:
      nsState = 'green'; ewState = 'red'; break;
    case 1:
      nsState = 'yellow'; ewState = 'red'; break;
    case 2:
      nsState = 'red'; ewState = 'green'; break;
    case 3:
      nsState = 'red'; ewState = 'yellow'; break;
    default:
      nsState = 'red'; ewState = 'red';
  }

  return [
    { direction: 'north', state: nsState },
    { direction: 'south', state: nsState },
    { direction: 'east', state: ewState },
    { direction: 'west', state: ewState },
  ];
}

/**
 * Generate synthetic vehicle positions from aggregate queue data
 * so the canvas can render a visual representation.
 */
function deriveVehicles(data: SimulationData): Vehicle[] {
  const vehicles: Vehicle[] = [];
  const distFromCenter = ROAD_WIDTH / 2 + 10;
  const spacing = 18;

  const configs: Record<Direction, { count: number; queueLen: number; axis: 'x' | 'y'; sign: number }> = {
    north: {
      count: data.vehicle_counts.north,
      queueLen: data.queue_lengths.north,
      axis: 'y', sign: -1,
    },
    south: {
      count: data.vehicle_counts.south,
      queueLen: data.queue_lengths.south,
      axis: 'y', sign: 1,
    },
    east: {
      count: data.vehicle_counts.east,
      queueLen: data.queue_lengths.east,
      axis: 'x', sign: 1,
    },
    west: {
      count: data.vehicle_counts.west,
      queueLen: data.queue_lengths.west,
      axis: 'x', sign: -1,
    },
  };

  for (const [dir, cfg] of Object.entries(configs) as [Direction, typeof configs.north][]) {
    const count = cfg.count;
    for (let i = 0; i < count; i++) {
      const isWaiting = i < cfg.queueLen;
      const offset = distFromCenter + (i + 1) * spacing;
      let x: number, y: number;

      if (cfg.axis === 'y') {
        x = CENTER + (dir === 'north' ? -12 : 12);
        y = CENTER + cfg.sign * offset;
      } else {
        x = CENTER + cfg.sign * offset;
        y = CENTER + (dir === 'east' ? 12 : -12);
      }

      // Clamp to canvas bounds
      x = Math.max(10, Math.min(CANVAS_SIZE - 10, x));
      y = Math.max(10, Math.min(CANVAS_SIZE - 10, y));

      vehicles.push({
        id: `${dir}-${i}`,
        x,
        y,
        direction: dir,
        speed: isWaiting ? 0 : data.avg_speeds[dir],
        color: isWaiting ? '#ff6b6b' : '#4a9eff',
        waiting: isWaiting,
      });
    }
  }

  return vehicles;
}

function getTrafficLightColor(light: TrafficLight | undefined): string {
  if (!light) return '#ff0000';
  switch (light.state) {
    case 'green': return '#00ff00';
    case 'yellow': return '#ffff00';
    case 'red': return '#ff0000';
  }
}

function drawRoads(ctx: CanvasRenderingContext2D) {
  ctx.fillStyle = '#555';
  // Horizontal road
  ctx.fillRect(0, CENTER - ROAD_WIDTH / 2, CANVAS_SIZE, ROAD_WIDTH);
  // Vertical road
  ctx.fillRect(CENTER - ROAD_WIDTH / 2, 0, ROAD_WIDTH, CANVAS_SIZE);

  // Intersection center
  ctx.fillStyle = '#666';
  ctx.fillRect(CENTER - ROAD_WIDTH / 2, CENTER - ROAD_WIDTH / 2, ROAD_WIDTH, ROAD_WIDTH);

  // Lane dividers (dashed)
  ctx.strokeStyle = '#aaa';
  ctx.lineWidth = 1;
  ctx.setLineDash([8, 8]);
  // Horizontal center line
  ctx.beginPath();
  ctx.moveTo(0, CENTER);
  ctx.lineTo(CENTER - ROAD_WIDTH / 2, CENTER);
  ctx.moveTo(CENTER + ROAD_WIDTH / 2, CENTER);
  ctx.lineTo(CANVAS_SIZE, CENTER);
  ctx.stroke();
  // Vertical center line
  ctx.beginPath();
  ctx.moveTo(CENTER, 0);
  ctx.lineTo(CENTER, CENTER - ROAD_WIDTH / 2);
  ctx.moveTo(CENTER, CENTER + ROAD_WIDTH / 2);
  ctx.lineTo(CENTER, CANVAS_SIZE);
  ctx.stroke();
  ctx.setLineDash([]);

  // Edge lines
  ctx.strokeStyle = '#fff';
  ctx.lineWidth = 2;
  // Horizontal road edges
  [CENTER - ROAD_WIDTH / 2, CENTER + ROAD_WIDTH / 2].forEach(y => {
    ctx.beginPath();
    ctx.moveTo(0, y);
    ctx.lineTo(CENTER - ROAD_WIDTH / 2, y);
    ctx.moveTo(CENTER + ROAD_WIDTH / 2, y);
    ctx.lineTo(CANVAS_SIZE, y);
    ctx.stroke();
  });
  // Vertical road edges
  [CENTER - ROAD_WIDTH / 2, CENTER + ROAD_WIDTH / 2].forEach(x => {
    ctx.beginPath();
    ctx.moveTo(x, 0);
    ctx.lineTo(x, CENTER - ROAD_WIDTH / 2);
    ctx.moveTo(x, CENTER + ROAD_WIDTH / 2);
    ctx.lineTo(x, CANVAS_SIZE);
    ctx.stroke();
  });
}

function drawTrafficLights(ctx: CanvasRenderingContext2D, lights: TrafficLight[]) {
  const positions: Record<string, [number, number]> = {
    north: [CENTER + ROAD_WIDTH / 2 + 12, CENTER - ROAD_WIDTH / 2 - 12],
    south: [CENTER - ROAD_WIDTH / 2 - 12, CENTER + ROAD_WIDTH / 2 + 12],
    east:  [CENTER + ROAD_WIDTH / 2 + 12, CENTER + ROAD_WIDTH / 2 + 12],
    west:  [CENTER - ROAD_WIDTH / 2 - 12, CENTER - ROAD_WIDTH / 2 - 12],
  };

  lights.forEach(light => {
    const pos = positions[light.direction];
    if (!pos) return;
    ctx.beginPath();
    ctx.arc(pos[0], pos[1], 8, 0, Math.PI * 2);
    ctx.fillStyle = getTrafficLightColor(light);
    ctx.fill();
    ctx.strokeStyle = '#000';
    ctx.lineWidth = 2;
    ctx.stroke();
  });
}

function drawVehicles(ctx: CanvasRenderingContext2D, vehicles: Vehicle[]) {
  vehicles.forEach(v => {
    ctx.fillStyle = v.color || '#4a9eff';
    const w = 20, h = 12;
    if (v.direction === 'north' || v.direction === 'south') {
      ctx.fillRect(v.x - w / 2, v.y - h / 2, w, h);
    } else {
      ctx.fillRect(v.x - h / 2, v.y - w / 2, h, w);
    }
  });
}

export default function IntersectionCanvas({ data }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    ctx.clearRect(0, 0, CANVAS_SIZE, CANVAS_SIZE);
    ctx.fillStyle = '#1a1a2e';
    ctx.fillRect(0, 0, CANVAS_SIZE, CANVAS_SIZE);

    drawRoads(ctx);

    if (data) {
      const lights = deriveTrafficLights(data.current_phase);
      drawTrafficLights(ctx, lights);
      const vehicles = deriveVehicles(data);
      drawVehicles(ctx, vehicles);
    }
  }, [data]);

  useEffect(() => {
    draw();
  }, [draw]);

  const phaseLabels: Record<number, string> = {
    0: 'N-S Green',
    1: 'N-S Yellow',
    2: 'E-W Green',
    3: 'E-W Yellow',
  };

  return (
    <div className="intersection-canvas">
      <h3>Intersection View</h3>
      {data && (
        <div className="phase-indicator">
          Phase: <span className="phase-name">{phaseLabels[data.current_phase] ?? `Phase ${data.current_phase}`}</span>
          {' '}({data.current_phase_duration}s)
        </div>
      )}
      <canvas
        ref={canvasRef}
        width={CANVAS_SIZE}
        height={CANVAS_SIZE}
        style={{ borderRadius: 8, border: '1px solid #333' }}
      />
    </div>
  );
}
