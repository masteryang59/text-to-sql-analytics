import { useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { formatFull, formatNumber, formatPeriod, formatShort, label, unitOf, type Unit } from "../format";
import type { Cell, ChartSpec, Column } from "../types";
import { buildChartData, labelEvery, niceTicks, SERIES_VARS, type ChartData } from "./data";

interface Props {
  spec: ChartSpec;
  columns: Column[];
  rows: Cell[][];
}

export function Chart({ spec, columns, rows }: Props) {
  if (spec.type === "number") return <NumberTile spec={spec} columns={columns} rows={rows} />;
  const data = buildChartData(spec, columns, rows);
  if (!data || data.x.length === 0) return null;
  const xColumn = columns.find((c) => c.name === spec.x)!;
  return spec.type === "line" ? (
    <LineChart data={data} xColumn={xColumn} />
  ) : (
    <BarChart data={data} xColumn={xColumn} horizontal={Boolean(spec.horizontal)} />
  );
}

function useWidth<T extends HTMLElement>(): [React.RefObject<T | null>, number] {
  const ref = useRef<T>(null);
  const [width, setWidth] = useState(640);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver(([entry]) => setWidth(Math.round(entry.contentRect.width)));
    ro.observe(el);
    setWidth(el.clientWidth || 640);
    return () => ro.disconnect();
  }, []);
  return [ref, width];
}

// --- number -------------------------------------------------------------------------

function NumberTile({ spec, columns, rows }: Props) {
  const col = columns.find((c) => c.name === spec.y[0]);
  if (!col || rows.length === 0) return null;
  const i = columns.indexOf(col);
  const value = rows[0][i];
  // A label next to the number, e.g. the winning category
  const context = columns
    .map((c, j) => (c.kind !== "number" && j !== i ? formatPeriod(rows[0][j], c.name) : null))
    .filter(Boolean)
    .join(" · ");
  return (
    <div className="tile">
      <div className="tile-label">{label(col.name)}</div>
      <div className="tile-value">{formatFull(value, col)}</div>
      {context && <div className="tile-context">{context}</div>}
    </div>
  );
}

// --- shared pieces ----------------------------------------------------------------------

function Legend({ data }: { data: ChartData }) {
  if (data.series.length < 2) return null;
  return (
    <ul className="legend" aria-label="Legend">
      {data.series.map((s, i) => (
        <li key={s.name}>
          <span className="key" style={{ background: SERIES_VARS[i] }} />
          {label(s.name)}
        </li>
      ))}
    </ul>
  );
}

interface Tip {
  left: number;
  top: number;
  content: ReactNode;
  side?: "above" | "right" | "left"; // above the point (default), or beside it
}

function Tooltip({ tip }: { tip: Tip | null }) {
  if (!tip) return null;
  return (
    <div className={`tooltip ${tip.side ?? "above"}`} style={{ left: tip.left, top: tip.top }} role="status">
      {tip.content}
    </div>
  );
}

function TipRows({ title, items, unit }: { title: string; items: { name: string; value: number | null; i: number }[]; unit: Unit }) {
  return (
    <>
      <div className="tip-title">{title}</div>
      {items.map((it) => (
        <div className="tip-row" key={it.name}>
          <span className="key" style={{ background: SERIES_VARS[it.i] }} />
          <span className="tip-name">{label(it.name)}</span>
          <span className="tip-value">{formatNumber(it.value, unit)}</span>
        </div>
      ))}
    </>
  );
}

function extent(data: ChartData): [number, number] {
  const all = data.series.flatMap((s) => s.values).filter((v): v is number => v !== null);
  return [Math.min(...all), Math.max(...all)];
}

// --- line ---------------------------------------------------------------------------------

const PAD = { top: 12, right: 16, bottom: 28, left: 56 };

function LineChart({ data, xColumn }: { data: ChartData; xColumn: Column }) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);
  const height = 260;
  const unit = unitOf(data.yColumn);
  const [lo, hi] = extent(data);
  const ticks = niceTicks(lo, hi);
  const y0 = ticks[0];
  const y1 = ticks[ticks.length - 1];
  const plotW = Math.max(width - PAD.left - PAD.right, 10);
  const plotH = height - PAD.top - PAD.bottom;
  const n = data.x.length;
  const xAt = (i: number) => PAD.left + (n === 1 ? plotW / 2 : (i / (n - 1)) * plotW);
  const yAt = (v: number) => PAD.top + plotH - ((v - y0) / (y1 - y0)) * plotH;
  const every = labelEvery(n, plotW, 64);
  const markers = n <= 16;

  const onMove = (e: React.PointerEvent<SVGRectElement>) => {
    const box = e.currentTarget.getBoundingClientRect();
    const rel = (e.clientX - box.left) / box.width;
    setHover(Math.max(0, Math.min(n - 1, Math.round(rel * (n - 1)))));
  };

  let tip: Tip | null = null;
  if (hover !== null) {
    // Beside the crosshair, on whichever side has room, so it never covers the text above the chart
    const x = xAt(hover);
    const right = x + 16 + 200 < width;
    tip = {
      side: right ? "right" : "left",
      left: right ? x + 16 : x - 16,
      top: PAD.top + plotH / 2,
      content: (
        <TipRows
          title={formatPeriod(data.x[hover], xColumn.name)}
          unit={unit}
          items={data.series.map((s, i) => ({ name: s.name, value: s.values[hover], i }))}
        />
      ),
    };
  }

  return (
    <div className="chart" ref={ref}>
      <Legend data={data} />
      <div className="plot">
        <svg width={width} height={height} role="img" aria-label={`Line chart of ${label(data.yColumn)} by ${label(xColumn.name)}`}>
          {ticks.map((t) => (
            <g key={t}>
              <line className="grid" x1={PAD.left} x2={PAD.left + plotW} y1={yAt(t)} y2={yAt(t)} />
              <text className="tick" x={PAD.left - 8} y={yAt(t)} dy="0.32em" textAnchor="end">
                {formatShort(t, unit)}
              </text>
            </g>
          ))}
          {data.x.map((v, i) =>
            i % every === 0 ? (
              <text key={i} className="tick" x={xAt(i)} y={height - 8} textAnchor={i === 0 && n > 1 ? "start" : "middle"}>
                {formatPeriod(v, xColumn.name)}
              </text>
            ) : null,
          )}
          {data.series.map((s, si) => {
            const path = s.values
              .map((v, i) => (v === null ? null : `${xAt(i)},${yAt(v)}`))
              .reduce<string[]>((acc, p, i, arr) => {
                if (p) acc.push(`${i === 0 || arr[i - 1] === null ? "M" : "L"}${p}`);
                return acc;
              }, [])
              .join("");
            return <path key={s.name} className="line" d={path} style={{ stroke: SERIES_VARS[si] }} />;
          })}
          {hover !== null && <line className="crosshair" x1={xAt(hover)} x2={xAt(hover)} y1={PAD.top} y2={PAD.top + plotH} />}
          {data.series.map((s, si) =>
            s.values.map((v, i) =>
              v !== null && (markers || i === hover || i === n - 1) ? (
                <circle key={`${s.name}-${i}`} className="dot" cx={xAt(i)} cy={yAt(v)} r={i === hover ? 5 : 4} style={{ fill: SERIES_VARS[si] }} />
              ) : null,
            ),
          )}
          <rect
            className="hit"
            x={PAD.left - 8}
            y={PAD.top}
            width={plotW + 16}
            height={plotH}
            onPointerMove={onMove}
            onPointerLeave={() => setHover(null)}
          />
        </svg>
        <Tooltip tip={tip} />
      </div>
    </div>
  );
}

// --- bar ------------------------------------------------------------------------------------

const BAR_MAX = 24;
const GAP = 2;

/** A bar with a 4px rounded data end and a square end at the baseline. */
function barPath(x: number, y: number, w: number, h: number, horizontal: boolean, negative: boolean): string {
  const r = Math.min(4, (horizontal ? w : h) / 2, (horizontal ? h : w) / 2);
  if (w <= 0 || h <= 0) return "";
  if (!horizontal) {
    if (!negative) // rounded top
      return `M${x},${y + h}V${y + r}Q${x},${y} ${x + r},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + h}Z`;
    return `M${x},${y}V${y + h - r}Q${x},${y + h} ${x + r},${y + h}H${x + w - r}Q${x + w},${y + h} ${x + w},${y + h - r}V${y}Z`;
  }
  if (!negative) // rounded right end
    return `M${x},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + h - r}Q${x + w},${y + h} ${x + w - r},${y + h}H${x}Z`;
  return `M${x + w},${y}H${x + r}Q${x},${y} ${x},${y + r}V${y + h - r}Q${x},${y + h} ${x + r},${y + h}H${x + w}Z`;
}

function BarChart({ data, xColumn, horizontal }: { data: ChartData; xColumn: Column; horizontal: boolean }) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<{ i: number; s: number } | null>(null);
  const unit = unitOf(data.yColumn);
  const [lo, hi] = extent(data);
  const ticks = niceTicks(lo, hi);
  const v0 = ticks[0];
  const v1 = ticks[ticks.length - 1];
  const n = data.x.length;
  const k = data.series.length;
  const xLabel = (v: Cell) => formatPeriod(v, xColumn.name);
  const single = k === 1;
  const showValues = single && n <= 14;

  // Horizontal: categories down the side, values across
  const labelW = horizontal ? Math.min(180, Math.max(60, ...data.x.map((v) => xLabel(v).length * 7 + 12))) : 0;
  const pad = horizontal
    ? { top: 4, right: showValues ? 64 : 16, bottom: 24, left: labelW }
    : { top: showValues ? 20 : 12, right: 16, bottom: 28, left: 56 };
  const band = horizontal ? Math.max(k * (Math.min(BAR_MAX, 18) + GAP) + 10, 26) : 0;
  const height = horizontal ? pad.top + pad.bottom + n * band : 260;
  const plotW = Math.max(width - pad.left - pad.right, 10);
  const plotH = height - pad.top - pad.bottom;
  const bandSize = horizontal ? band : plotW / n;
  const barSize = Math.max(2, Math.min(BAR_MAX, (bandSize * 0.7 - GAP * (k - 1)) / k));
  const groupSize = k * barSize + (k - 1) * GAP;
  const scale = (v: number) => ((v - v0) / (v1 - v0)) * (horizontal ? plotW : plotH);
  const zero = scale(0);
  const every = horizontal ? 1 : labelEvery(n, plotW, 72);

  const bars = data.x.flatMap((_, i) =>
    data.series.map((s, si) => {
      const v = s.values[i];
      if (v === null) return null;
      const offset = (bandSize - groupSize) / 2 + si * (barSize + GAP);
      const len = Math.abs(scale(v) - zero);
      const negative = v < 0;
      let x: number, y: number, w: number, h: number;
      if (horizontal) {
        y = pad.top + i * bandSize + offset;
        h = barSize;
        x = pad.left + (negative ? zero - len : zero);
        w = len;
      } else {
        x = pad.left + i * bandSize + offset;
        w = barSize;
        y = pad.top + plotH - (negative ? zero : zero + len);
        h = len;
      }
      return { i, si, v, x, y, w, h, negative };
    }),
  ).filter((b): b is NonNullable<typeof b> => b !== null);

  let tip: Tip | null = null;
  if (hover) {
    const b = bars.find((bb) => bb.i === hover.i && bb.si === hover.s);
    if (b) {
      // Beside the bar end when there's room, so it doesn't cover the neighbouring bars
      const right = horizontal && b.x + b.w + 56 + 190 < width;
      const groupMid = horizontal ? pad.top + hover.i * bandSize + bandSize / 2 : 0;
      tip = {
        side: right ? "right" : "above",
        left: right ? b.x + b.w + 56 : Math.min(Math.max(horizontal ? b.x + b.w : b.x + b.w / 2, 90), width - 90),
        top: right ? groupMid : Math.max(0, b.y - 8),
        content: (
          <TipRows
            title={xLabel(data.x[hover.i])}
            unit={unit}
            items={data.series.map((s, si) => ({ name: s.name, value: s.values[hover.i], i: si }))}
          />
        ),
      };
    }
  }

  return (
    <div className="chart" ref={ref}>
      <Legend data={data} />
      <div className="plot">
        <svg width={width} height={height} role="img" aria-label={`Bar chart of ${label(data.yColumn)} by ${label(xColumn.name)}`}>
          {ticks.map((t) => {
            const p = scale(t);
            return horizontal ? (
              <g key={t}>
                <line className="grid" x1={pad.left + p} x2={pad.left + p} y1={pad.top} y2={pad.top + plotH} />
                <text className="tick" x={pad.left + p} y={height - 6} textAnchor="middle">{formatShort(t, unit)}</text>
              </g>
            ) : (
              <g key={t}>
                <line className="grid" x1={pad.left} x2={pad.left + plotW} y1={pad.top + plotH - p} y2={pad.top + plotH - p} />
                <text className="tick" x={pad.left - 8} y={pad.top + plotH - p} dy="0.32em" textAnchor="end">{formatShort(t, unit)}</text>
              </g>
            );
          })}
          {data.x.map((v, i) =>
            horizontal ? (
              <text key={i} className="tick cat" x={pad.left - 8} y={pad.top + i * bandSize + bandSize / 2} dy="0.32em" textAnchor="end">
                {truncate(xLabel(v), 24)}
              </text>
            ) : i % every === 0 ? (
              <text key={i} className="tick cat" x={pad.left + i * bandSize + bandSize / 2} y={height - 8} textAnchor="middle">
                {truncate(xLabel(v), Math.max(6, Math.floor((bandSize * every) / 7)))}
              </text>
            ) : null,
          )}
          {bars.map((b) => (
            <path
              key={`${b.i}-${b.si}`}
              className={`bar${hover && (hover.i !== b.i) ? " dim" : ""}`}
              d={barPath(b.x, b.y, b.w, b.h, horizontal, b.negative)}
              style={{ fill: SERIES_VARS[b.si] }}
            />
          ))}
          {showValues &&
            bars.map((b) =>
              horizontal ? (
                <text key={`v${b.i}`} className="value" x={b.x + b.w + 6} y={b.y + b.h / 2} dy="0.32em">{formatShort(b.v, unit)}</text>
              ) : (
                <text key={`v${b.i}`} className="value" x={b.x + b.w / 2} y={b.y - 6} textAnchor="middle">{formatShort(b.v, unit)}</text>
              ),
            )}
          <line
            className="axis"
            x1={horizontal ? pad.left + zero : pad.left}
            x2={horizontal ? pad.left + zero : pad.left + plotW}
            y1={horizontal ? pad.top : pad.top + plotH - zero}
            y2={horizontal ? pad.top + plotH : pad.top + plotH - zero}
          />
          {/* hit targets: the whole band of each category, bigger than the bars */}
          {data.x.map((_, i) => (
            <rect
              key={`h${i}`}
              className="hit"
              x={horizontal ? pad.left : pad.left + i * bandSize}
              y={horizontal ? pad.top + i * bandSize : pad.top}
              width={horizontal ? plotW : bandSize}
              height={horizontal ? bandSize : plotH}
              onPointerEnter={() => setHover({ i, s: 0 })}
              onPointerLeave={() => setHover(null)}
            />
          ))}
        </svg>
        <Tooltip tip={tip} />
      </div>
    </div>
  );
}

function truncate(s: string, max: number): string {
  return s.length > max ? `${s.slice(0, Math.max(1, max - 1))}…` : s;
}

export function cancelJob(data: unknown): unknown {
  if (!data) return null;
  return data;
}

export function sendNotification(data: unknown): unknown {
  if (!data) return null;
  return data;
}

export function cancelJob(data: unknown): unknown {
  if (!data) return null;
  return data;
}

export function sendNotification(data: unknown): unknown {
  if (!data) return null;
  return data;
}