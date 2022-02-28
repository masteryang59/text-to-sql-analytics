import { useEffect, useRef, useState } from "react";
import * as api from "./api";
import { AnswerCard } from "./components/AnswerCard";
import { SchemaPanel } from "./components/SchemaPanel";
import type { Meta, SchemaTable, Turn } from "./types";

const HISTORY_TURNS = 4;

function formatDay(iso: string | null): string {
  if (!iso) return "?";
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d)).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
}

export default function App() {
  const [meta, setMeta] = useState<Meta | null>(null);
  const [tables, setTables] = useState<SchemaTable[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState("");
  const [sidebar, setSidebar] = useState(false);
  const nextId = useRef(1);
  const endRef = useRef<HTMLDivElement>(null);
  const busy = turns.some((t) => t.answer === null && !t.failed);

  useEffect(() => {
    Promise.all([api.getMeta(), api.getSchema()])
      .then(([m, s]) => {
        setMeta(m);
        setTables(s.tables);
      })
      .catch((e: Error) => setLoadError(e.message));
  }, []);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [turns.length]);

  const update = (id: number, patch: Partial<Turn>) =>
    setTurns((ts) => ts.map((t) => (t.id === id ? { ...t, ...patch } : t)));

  const submit = async (question: string) => {
    const q = question.trim();
    if (!q || busy) return;
    setInput("");
    setSidebar(false);
    // Earlier questions and their SQL, so follow-ups like "now by region" work
    const history = turns
      .filter((t) => t.answer && t.answer.status !== "error")
      .slice(-HISTORY_TURNS)
      .map((t) => ({ question: t.question, sql: t.answer!.sql }));
    const id = nextId.current++;
    setTurns((ts) => [...ts, { id, question: q, answer: null }]);
    try {
      update(id, { answer: await api.ask(q, history) });
    } catch (e) {
      update(id, { failed: (e as Error).message });
    }
  };

  const runSql = async (id: number, sql: string) => {
    try {
      const answer = await api.runSql(sql);
      update(id, { answer: { ...answer, explanation: "" }, edited: true });
    } catch (e) {
      update(id, { failed: (e as Error).message });
    }
  };

  return (
    <div className={`app${sidebar ? " sidebar-open" : ""}`}>
      <aside className="sidebar">
        <div className="brand">
          <span className="logo" aria-hidden="true" />
          <div>
            <h1>Sales Analytics Chat</h1>
            <p className="sub">Plain English in, SQL out</p>
          </div>
        </div>
        {meta && (
          <dl className="facts">
            <div>
              <dt>Model</dt>
              <dd>
                <span className={`badge${meta.llm ? " llm" : ""}`}>{meta.llm ? meta.generator.replace(/^llm:/, "") : "Offline parser"}</span>
              </dd>
            </div>
            <div>
              <dt>Data</dt>
              <dd>{formatDay(meta.data_start)} – {formatDay(meta.data_end)}</dd>
            </div>
            <div>
              <dt>“Today”</dt>
              <dd>{formatDay(meta.today)}</dd>
            </div>
          </dl>
        )}
        {meta && (
          <section className="suggestions" aria-label="Example questions">
            <h2>Try asking</h2>
            <ul>
              {meta.suggestions.map((s) => (
                <li key={s}>
                  <button type="button" disabled={busy} onClick={() => submit(s)}>{s}</button>
                </li>
              ))}
            </ul>
          </section>
        )}
        <SchemaPanel tables={tables} />
      </aside>

      <main className="main">
        <header className="topbar">
          <button type="button" className="ghost menu" aria-label="Show schema and examples" onClick={() => setSidebar(!sidebar)}>
            ☰
          </button>
          <span className="topbar-title">Ask the sales database</span>
          {turns.length > 0 && (
            <button type="button" className="ghost" disabled={busy} onClick={() => setTurns([])}>
              New conversation
            </button>
          )}
        </header>

        <div className="thread">
          {loadError && <div className="card error-card">Couldn't reach the API: {loadError}</div>}
          {turns.length === 0 && !loadError && (
            <div className="welcome">
              <h2>Ask a question about sales</h2>
              <p>
                Questions become one read-only PostgreSQL query. You see the SQL, the rows and a chart, and you can
                edit the SQL and run it again. Follow-ups like “now by region” or “only 2025” refine the last answer.
              </p>
              {meta && !meta.llm && (
                <p className="hint">
                  No language model is configured, so a rule-based parser writes the SQL. It handles measures by
                  dimension, time periods, rankings and filters, and says so when a question is beyond it.
                </p>
              )}
            </div>
          )}
          {turns.map((t) => (
            <AnswerCard key={t.id} turn={t} onRunSql={runSql} />
          ))}
          <div ref={endRef} />
        </div>

        <form
          className="composer"
          onSubmit={(e) => {
            e.preventDefault();
            submit(input);
          }}
        >
          <textarea
            value={input}
            rows={1}
            maxLength={1000}
            placeholder={turns.length ? "Ask a follow-up, e.g. “now by channel”" : "e.g. Top 5 products by revenue last quarter"}
            aria-label="Question"
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                submit(input);
              }
            }}
          />
          <button type="submit" className="primary" disabled={busy || !input.trim()}>
            Ask
          </button>
        </form>
      </main>
    </div>
  );
}

export function generateReport(data: unknown): unknown {
  if (!data) return null;
  return data;
}

export function cleanupResources(data: unknown): unknown {
  if (!data) return null;
  return data;
}

export function generateReport(data: unknown): unknown {
  if (!data) return null;
  return data;
}