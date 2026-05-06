import { useRef, useEffect, useCallback, useMemo } from 'react';
import type { IntersectionState, Direction, LightState } from '../types';

interface Props {
  intersections: IntersectionState[];
  time: number;
}

const CELL_W = 220;
const CELL_H = 180;
const ROAD_W = 40;
const ROAD_H = ROAD_W;

/** Cell origin (top-left of intersection box) */
function cellOrigin(row: number, col: number): [number, number] {
  const x = col * CELL_W + (col + 1) * ROAD_W;
  const y = row * CELL_H + (row + 1) * ROAD_H;
  return [x, y];
}

function deriveLights(phase: number): Record<Direction, LightState> {
  switch (phase) {
    case 0: return { north: 'green', south: 'green', east: 'red', west: 'red' };
    case 1: return { north: 'yellow', south: 'yellow', east: 'red', west: 'red' };
    case 2: return { north: 'red', south: 'red', east: 'green', west: 'green' };
    case 3: return { north: 'red', south: 'red', east: 'yellow', west: 'yellow' };
    default: return { north: 'red', south: 'red', east: 'red', west: 'red' };
  }
}

function lightColor(s: LightState): string {
  return s === 'green' ? '#00e676' : s === 'yellow' ? '#ffea00' : '#ff1744';
}

function congestionColor(level: number): string {
  if (level <= 0.5) {
    const t = level * 2;
    const r = Math.round(t * 255);
    return `rgb(${r}, 200, 0)`;
  } else {
    const t = (level - 0.5) * 2;
    const g = Math.round((1 - t) * 200);
    return `rgb(255, ${g}, 0)`;
  }
}

export default function GridCanvas({ intersections, time }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const animRef = useRef<number>(0);
  const timeRef = useRef(time);

  // Compute grid dimensions from intersections
  const { gridRows, gridCols, canvasW, canvasH } = useMemo(() => {
    const count = intersections.length;
    if (count === 0) return { gridRows: 1, gridCols: 1, canvasW: 300, canvasH: 260 };
    const cols = Math.ceil(Math.sqrt(count));
    const rows = Math.ceil(count / cols);
    const w = cols * CELL_W + (cols + 1) * ROAD_W;
    const h = rows * CELL_H + (rows + 1) * ROAD_H;
    return { gridRows: rows, gridCols: cols, canvasW: w, canvasH: h };
  }, [intersections.length]);

  useEffect(() => {
    timeRef.current = time;
  }, [time]);

  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    // Background
    ctx.fillStyle = '#0f0f1a';
    ctx.fillRect(0, 0, canvasW, canvasH);

    // Roads
    ctx.fillStyle = '#3a3a5c';
    for (let r = 0; r <= gridRows; r++) {
      const y = r * CELL_H + r * ROAD_H;
      ctx.fillRect(0, y, canvasW, ROAD_H);
    }
    for (let c = 0; c <= gridCols; c++) {
      const x = c * CELL_W + c * ROAD_W;
      ctx.fillRect(x, 0, ROAD_W, canvasH);
    }

    // Center lines
    ctx.strokeStyle = '#666';
    ctx.lineWidth = 1;
    ctx.setLineDash([6, 6]);
    for (let r = 0; r <= gridRows; r++) {
      const y = r * CELL_H + r * ROAD_H + ROAD_H / 2;
      ctx.beginPath();
      ctx.moveTo(0, y);
      ctx.lineTo(canvasW, y);
      ctx.stroke();
    }
    for (let c = 0; c <= gridCols; c++) {
      const x = c * CELL_W + c * ROAD_W + ROAD_W / 2;
      ctx.beginPath();
      ctx.moveTo(x, 0);
      ctx.lineTo(x, canvasH);
      ctx.stroke();
    }
    ctx.setLineDash([]);

    // Intersections
    for (const inter of intersections) {
      const [ox, oy] = cellOrigin(inter.row, inter.col);
      const cx = ox + CELL_W / 2;
      const cy = oy + CELL_H / 2;
      const halfRoad = ROAD_W / 2;

      const glow = congestionColor(inter.congestion_level);
      ctx.fillStyle = glow + '22';
      ctx.fillRect(ox, oy, CELL_W, CELL_H);

      ctx.fillStyle = '#2a2a4a';
      ctx.fillRect(cx - halfRoad, cy - halfRoad, ROAD_W, ROAD_W);

      const lights = deriveLights(inter.current_phase);
      const lightPositions: Record<Direction, [number, number]> = {
        north: [cx, cy - halfRoad - 10],
        south: [cx, cy + halfRoad + 10],
        east: [cx + halfRoad + 10, cy],
        west: [cx - halfRoad - 10, cy],
      };

      for (const dir of ['north', 'south', 'east', 'west'] as Direction[]) {
        const [lx, ly] = lightPositions[dir];
        ctx.beginPath();
        ctx.arc(lx, ly, 6, 0, Math.PI * 2);
        ctx.fillStyle = lightColor(lights[dir]);
        ctx.fill();
        ctx.strokeStyle = '#000';
        ctx.lineWidth = 1.5;
        ctx.stroke();
      }

      ctx.font = 'bold 11px monospace';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';

      const ql = inter.queue_lengths;
      ctx.fillStyle = '#ff8a80';
      ctx.fillText(`${ql.north || 0}`, cx, oy + 12);
      ctx.fillStyle = '#80cbc4';
      ctx.fillText(`${ql.south || 0}`, cx, oy + CELL_H - 12);
      ctx.fillStyle = '#fff59d';
      ctx.fillText(`${ql.east || 0}`, ox + CELL_W - 14, cy);
      ctx.fillStyle = '#b39ddb';
      ctx.fillText(`${ql.west || 0}`, ox + 14, cy);

      ctx.fillStyle = '#fff';
      ctx.font = 'bold 12px sans-serif';
      ctx.fillText(inter.id, cx, cy);

      ctx.strokeStyle = glow;
      ctx.lineWidth = 3;
      ctx.beginPath();
      ctx.arc(cx, cy, halfRoad + 3, 0, Math.PI * 2);
      ctx.stroke();
    }

    // Vehicles
    const speed = 60;
    for (const inter of intersections) {
      const [ox, oy] = cellOrigin(inter.row, inter.col);
      const cx = ox + CELL_W / 2;
      const cy = oy + CELL_H / 2;

      const totalVehicles = (inter.vehicle_counts.north || 0) + (inter.vehicle_counts.south || 0)
        + (inter.vehicle_counts.east || 0) + (inter.vehicle_counts.west || 0);

      const seed = inter.row * 10 + inter.col;
      const numDots = Math.min(totalVehicles, 12);

      for (let i = 0; i < numDots; i++) {
        const phase = ((timeRef.current * speed + i * 40 + seed * 100) % (CELL_W + CELL_H)) / (CELL_W + CELL_H);
        let vx: number, vy: number;

        const approach = i % 4;
        if (approach === 0) {
          vx = cx - 6;
          vy = oy - ROAD_H * phase;
        } else if (approach === 1) {
          vx = cx + 6;
          vy = oy + CELL_H + ROAD_H * phase;
        } else if (approach === 2) {
          vx = ox + CELL_W + ROAD_W * phase;
          vy = cy - 6;
        } else {
          vx = ox - ROAD_W * phase;
          vy = cy + 6;
        }

        ctx.beginPath();
        ctx.arc(vx, vy, 3, 0, Math.PI * 2);
        ctx.fillStyle = approach < 2 ? '#4a9eff' : '#ff9800';
        ctx.fill();
      }
    }
  }, [intersections, gridRows, gridCols, canvasW, canvasH]);

  useEffect(() => {
    draw();
  }, [draw]);

  useEffect(() => {
    let running = true;
    const animate = () => {
      if (!running) return;
      timeRef.current += 0.016;
      draw();
      animRef.current = requestAnimationFrame(animate);
    };
    animRef.current = requestAnimationFrame(animate);
    return () => {
      running = false;
      cancelAnimationFrame(animRef.current);
    };
  }, [draw]);

  return (
    <div className="grid-canvas">
      <h3>🚦 Grid View ({gridCols}×{gridRows})</h3>
      <canvas
        ref={canvasRef}
        width={canvasW}
        height={canvasH}
        style={{ borderRadius: 8, border: '1px solid #2a2a4a', width: '100%', height: 'auto' }}
      />
    </div>
  );
}
