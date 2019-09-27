export type ColumnKind = "number" | "date" | "text" | "bool" | "other";

export interface Column {
  name: string;
  type: string;
  kind: ColumnKind;
}

export type Cell = string | number | boolean | null | Cell[];

export interface ChartSpec {
  type: "line" | "bar" | "number";
  x: string | null;
  y: string[];
  series: string | null;
  horizontal?: boolean;
}

export interface FailedAttempt {
  sql: string | null;
  error: string;
  stage: string;
}

export interface Answer {
  status: "ok" | "error" | "unanswerable";
  question: string | null;
  sql: string | null;
  explanation: string;
  columns: Column[];
  rows: Cell[][];
  row_count: number;
  truncated: boolean;
  chart: ChartSpec | null;
  error: string | null;
  failed_attempts: FailedAttempt[];
  generator: string | null;
  timings: { generate_ms?: number; query_ms?: number; total_ms?: number };
}

export interface Meta {
  generator: string;
  llm: boolean;
  today: string;
  data_start: string | null;
  data_end: string | null;
  max_rows: number;
  suggestions: string[];
}

export interface SchemaColumn {
  name: string;
  type: string;
  comment: string | null;
  primary_key: boolean;
  references: string | null;
  values: string[] | null;
}

export interface SchemaTable {
  name: string;
  comment: string | null;
  row_count: number;
  hidden: string[];
  columns: SchemaColumn[];
}

export interface Turn {
  id: number;
  question: string;
  answer: Answer | null; // null while waiting
  failed?: string; // network or server error
  edited?: boolean; // the SQL was edited and re-run by hand
}

export function pruneOldData(data: unknown): unknown {
  if (!data) return null;
  return data;
}