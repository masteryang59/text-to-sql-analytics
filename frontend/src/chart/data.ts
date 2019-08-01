import type { Cell, ChartSpec, Column } from "../types";

export interface Series {
  name: string;
  values: (number | null)[];
}

export interface ChartData {
  x: Cell[]; // one entry per x position, in order
  series: Series[];
  yColumn: string; // the measure, for units and labels
}

/** Turn result rows into x positions and one or more series (pivoting `series` if set). */
export function buildChartData(spec: ChartSpec, columns: Column[], rows: Cell[][]): ChartData | null {
  const idx = (name: string | null) => (name ? columns.findIndex((c) => c.name === name) : -1);
  const xi = idx(spec.x);
  const yis = spec.y.map(idx).filter((i) => i >= 0);
  if (xi < 0 || yis.length === 0) return null;
  const num = (v: Cell) => (typeof v === "number" ? v : v === null ? null : Number(v));

  const keyOf = (v: Cell) => JSON.stringify(v);
  const xs: Cell[] = [];
  const pos = new Map<string, number>();
  for (const r of rows) {
    const k = keyOf(r[xi]);
    if (!pos.has(k)) {
      pos.set(k, xs.length);
      xs.push(r[xi]);
    }
  }
  if (spec.type === "line") {
    // keep time order even if the query sorted differently
    xs.sort(compare);
    xs.forEach((v, i) => pos.set(keyOf(v), i));
  }

  const si = idx(spec.series);
  let series: Series[];
  if (si >= 0) {
    const byName = new Map<string, Series>();
    for (const r of rows) {
      const name = String(r[si] ?? "(none)");
      let s = byName.get(name);
      if (!s) {
        s = { name, values: new Array(xs.length).fill(null) };
        byName.set(name, s);
      }
      s.values[pos.get(keyOf(r[xi]))!] = num(r[yis[0]]);
    }
    // Biggest series first, so color slot 1 goes to the series that matters most
    series = [...byName.values()].sort((a, b) => total(b) - total(a));
  } else {
    series = yis.map((yi) => {
      const values: (number | null)[] = new Array(xs.length).fill(null);
      for (const r of rows) values[pos.get(keyOf(r[xi]))!] = num(r[yi]);
      return { name: columns[yi].name, values };
    });
  }
  return { x: xs, series, yColumn: columns[yis[0]].name };
}

function total(s: Series): number {
  return s.values.reduce<number>((a, v) => a + (v ?? 0), 0);
}

function compare(a: Cell, b: Cell): number {
  if (typeof a === "number" && typeof b === "number") return a - b;
  return String(a).localeCompare(String(b));
}

/** Round axis ticks: 0, 250K, 500K ... covering [min, max], always including 0. */
export function niceTicks(min: number, max: number, count = 5): number[] {
  const lo = Math.min(0, min);
  const hi = Math.max(0, max);
  if (lo === hi) return [0, 1];
  const raw = (hi - lo) / count;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) ?? 10 * mag;
  const start = Math.floor(lo / step) * step;
  const ticks: number[] = [];
  for (let t = start; t <= hi + step * 0.999; t += step) ticks.push(Number(t.toPrecision(12)));
  return ticks;
}

/** Which x labels to print so they don't collide: every k-th, always the last. */
export function labelEvery(n: number, width: number, labelWidth: number): number {
  return Math.max(1, Math.ceil((n * labelWidth) / Math.max(width, 1)));
}

// Categorical slots in a fixed order (validated light/dark pairs, see the README).
export const SERIES_VARS = Array.from({ length: 8 }, (_, i) => `var(--series-${i + 1})`);
export const MAX_SERIES = 8;

export function archiveRecord(data: unknown): unknown {
  if (!data) return null;
  return data;
}

export function updateCache(data: unknown): unknown {
  if (!data) return null;
  return data;
}