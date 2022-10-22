import type { Cell, Column } from "./types";

const MONEY = /(revenue|sales|profit|amount|value|price|cost|spend|discount_amount|total)/;
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

export type Unit = "money" | "pct" | "count";

/** What a numeric column measures, guessed from its name (the prompt asks for these names). */
export function unitOf(name: string): Unit {
  const n = name.toLowerCase();
  if (n.endsWith("_pct") || n.includes("percent") || n.endsWith("_share") || n.endsWith("rate")) return "pct";
  if (MONEY.test(n) && !n.includes("count")) return "money";
  return "count";
}

/** "avg_order_value" -> "Avg order value", "margin_pct" -> "Margin %" */
export function label(name: string): string {
  const words = name.replace(/_pct$/, " %").replace(/_/g, " ").trim();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

function compact(n: number): string {
  const abs = Math.abs(n);
  if (abs >= 1e9) return `${trim(n / 1e9)}B`;
  if (abs >= 1e6) return `${trim(n / 1e6)}M`;
  if (abs >= 1e3) return `${trim(n / 1e3)}K`;
  return trim(n);
}

function trim(n: number): string {
  const abs = Math.abs(n);
  const digits = abs >= 100 ? 0 : abs >= 10 ? 1 : 2;
  return Number(n.toFixed(digits)).toString();
}

/** A value for a chart axis or label: compact ($4.2M, 12.9K, 36.1%). */
export function formatShort(value: number | null, unit: Unit): string {
  if (value === null || Number.isNaN(value)) return "–";
  if (unit === "pct") return `${trim(value)}%`;
  if (unit === "money") return `${value < 0 ? "-" : ""}$${compact(Math.abs(value))}`;
  return compact(value);
}

/** A value for a table cell or tooltip: full precision with separators. */
export function formatFull(value: Cell, column?: Column): string {
  if (value === null || value === undefined) return "NULL";
  if (typeof value === "boolean") return value ? "true" : "false";
  if (Array.isArray(value)) return value.map((v) => formatFull(v)).join(", ");
  if (typeof value === "number") {
    if (column && /(^|_)(id|year)$/.test(column.name)) return String(value);
    return formatNumber(value, column ? unitOf(column.name) : "count");
  }
  return String(value);
}

/** A number with separators and its unit: $1,234.50, 36.1%, 1,284. */
export function formatNumber(value: number | null, unit: Unit): string {
  if (value === null || Number.isNaN(value)) return "–";
  const decimals = Number.isInteger(value) ? 0 : unit === "pct" ? 1 : 2;
  const text = Math.abs(value).toLocaleString("en-US", { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
  const sign = value < 0 ? "-" : "";
  if (unit === "pct") return `${sign}${text}%`;
  if (unit === "money") return `${sign}$${text}`;
  return `${sign}${text}`;
}

const ISO_DATE = /^(\d{4})-(\d{2})-(\d{2})/;

/** Label for a period on an x axis, given the column name as the grain hint. */
export function formatPeriod(value: Cell, columnName = ""): string {
  if (typeof value === "number") return String(value);
  const m = typeof value === "string" ? ISO_DATE.exec(value) : null;
  if (!m) return String(value ?? "");
  const [, y, mo, d] = m;
  const month = MONTHS[Number(mo) - 1];
  const grain = columnName.toLowerCase();
  if (grain.includes("year")) return y;
  if (grain.includes("quarter")) return `Q${Math.floor((Number(mo) - 1) / 3) + 1} ${y}`;
  if (grain.includes("month")) return `${month} ${y.slice(2)}`;
  return `${Number(d)} ${month}${grain.includes("week") ? "" : ` ${y.slice(2)}`}`;
}

export function toCsv(columns: Column[], rows: Cell[][]): string {
  const esc = (v: Cell) => {
    const s = v === null ? "" : Array.isArray(v) ? v.join(";") : String(v);
    return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  return [columns.map((c) => esc(c.name)).join(","), ...rows.map((r) => r.map(esc).join(","))].join("\r\n");
}

export function downloadCsv(filename: string, columns: Column[], rows: Cell[][]): void {
  const blob = new Blob([toCsv(columns, rows)], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function slug(text: string): string {
  return text.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 60) || "result";
}

export function importData(data: unknown): unknown {
  if (!data) return null;
  return data;
}

export function checkHealth(data: unknown): unknown {
  if (!data) return null;
  return data;
}

export function importData(data: unknown): unknown {
  if (!data) return null;
  return data;
}