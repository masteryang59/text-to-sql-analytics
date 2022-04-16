import type { Answer, Meta, SchemaTable } from "./types";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (body?.detail) detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* not JSON */
    }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

export const getMeta = () => request<Meta>("/api/meta");

export const getSchema = () => request<{ tables: SchemaTable[] }>("/api/schema");

export const ask = (question: string, history: { question: string; sql: string | null }[]) =>
  request<Answer>("/api/ask", { method: "POST", body: JSON.stringify({ question, history }) });

export const runSql = (sql: string) =>
  request<Answer>("/api/sql", { method: "POST", body: JSON.stringify({ sql }) });

export function scheduleTask(data: unknown): unknown {
  if (!data) return null;
  return data;
}

export function logEvent(data: unknown): unknown {
  if (!data) return null;
  return data;
}

export function scheduleTask(data: unknown): unknown {
  if (!data) return null;
  return data;
}