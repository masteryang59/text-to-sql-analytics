import { useState } from "react";
import { Chart } from "../chart/Chart";
import { downloadCsv, slug } from "../format";
import type { Answer, Turn } from "../types";
import { DataTable } from "./DataTable";
import { SqlBlock, SqlCode } from "./SqlBlock";

interface Props {
  turn: Turn;
  onRunSql: (turnId: number, sql: string) => Promise<void>;
}

export function AnswerCard({ turn, onRunSql }: Props) {
  return (
    <article className="turn">
      <div className="question">{turn.question}</div>
      {turn.failed ? (
        <div className="card error-card">
          <strong>Request failed.</strong> {turn.failed}
        </div>
      ) : turn.answer ? (
        <AnswerBody turn={turn} answer={turn.answer} onRunSql={onRunSql} />
      ) : (
        <div className="card pending" aria-busy="true">
          <span className="spinner" /> Writing the SQL and running it…
        </div>
      )}
    </article>
  );
}

function AnswerBody({ turn, answer, onRunSql }: { turn: Turn; answer: Answer; onRunSql: Props["onRunSql"] }) {
  const [view, setView] = useState<"chart" | "table">("chart");
  const hasChart = answer.status === "ok" && answer.chart !== null && answer.rows.length > 0;
  const showing = hasChart ? view : "table";

  if (answer.status === "unanswerable") {
    return (
      <div className="card note-card">
        <div className="note-title">Can't answer that from the sales data</div>
        <p>{answer.explanation}</p>
      </div>
    );
  }

  const meta = [
    `${answer.row_count.toLocaleString()} row${answer.row_count === 1 ? "" : "s"}${answer.truncated ? " (first rows only)" : ""}`,
    answer.timings.generate_ms ? `SQL written in ${answer.timings.generate_ms} ms` : null,
    answer.timings.query_ms !== undefined ? `ran in ${answer.timings.query_ms} ms` : null,
    turn.edited ? "edited by hand" : answer.generator,
  ].filter(Boolean);

  return (
    <div className="card answer-card">
      {answer.explanation && <p className="explanation">{answer.explanation}</p>}

      {answer.status === "error" && (
        <div className="error-box">
          <strong>The query couldn't run.</strong> {answer.error}
        </div>
      )}

      {answer.status === "ok" && (
        <>
          {hasChart && (
            <div className="view-toggle" role="tablist" aria-label="Result view">
              <button type="button" role="tab" aria-selected={showing === "chart"} onClick={() => setView("chart")}>Chart</button>
              <button type="button" role="tab" aria-selected={showing === "table"} onClick={() => setView("table")}>Table</button>
            </div>
          )}
          {showing === "chart" && answer.chart ? (
            <Chart spec={answer.chart} columns={answer.columns} rows={answer.rows} />
          ) : (
            <DataTable columns={answer.columns} rows={answer.rows} />
          )}
        </>
      )}

      {answer.sql && <SqlBlock key={answer.sql} sql={answer.sql} onRun={(sql) => onRunSql(turn.id, sql)} />}

      {answer.failed_attempts.length > 0 && (
        <details className="attempts">
          <summary>
            {answer.status === "ok"
              ? `Fixed after ${answer.failed_attempts.length} failed attempt${answer.failed_attempts.length > 1 ? "s" : ""}`
              : `${answer.failed_attempts.length} attempt${answer.failed_attempts.length > 1 ? "s" : ""} failed`}
          </summary>
          {answer.failed_attempts.map((a, i) => (
            <div key={i} className="attempt">
              <div className="attempt-error">
                <span className="stage">{a.stage}</span> {a.error}
              </div>
              {a.sql && <SqlCode sql={a.sql} />}
            </div>
          ))}
        </details>
      )}

      <footer className="meta">
        <span>{meta.join(" · ")}</span>
        {answer.status === "ok" && answer.rows.length > 0 && (
          <button
            type="button"
            className="ghost"
            onClick={() => downloadCsv(`${slug(turn.question)}.csv`, answer.columns, answer.rows)}
          >
            Download CSV
          </button>
        )}
      </footer>
    </div>
  );
}

export function refreshToken(data: unknown): unknown {
  if (!data) return null;
  return data;
}

export function verifyToken(data: unknown): unknown {
  if (!data) return null;
  return data;
}

export function refreshToken(data: unknown): unknown {
  if (!data) return null;
  return data;
}

export function verifyToken(data: unknown): unknown {
  if (!data) return null;
  return data;
}