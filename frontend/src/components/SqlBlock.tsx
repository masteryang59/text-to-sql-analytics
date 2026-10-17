import { useState } from "react";
import { tokenize } from "../sql";

export function SqlCode({ sql }: { sql: string }) {
  return (
    <pre className="sql">
      <code>
        {tokenize(sql).map((t, i) =>
          t.type === "plain" ? t.text : <span key={i} className={`t-${t.type}`}>{t.text}</span>,
        )}
      </code>
    </pre>
  );
}

interface Props {
  sql: string;
  onRun: (sql: string) => Promise<void>;
}

/** The generated SQL with copy, and an editor to change it and run it again. */
export function SqlBlock({ sql, onRun }: Props) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(sql);
  const [copied, setCopied] = useState(false);
  const [running, setRunning] = useState(false);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(sql);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard blocked; the text is selectable anyway */
    }
  };

  const run = async () => {
    setRunning(true);
    try {
      await onRun(draft);
      setEditing(false);
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="sql-block">
      <div className="sql-head">
        <span className="sql-title">SQL</span>
        <div className="sql-actions">
          {!editing && (
            <button type="button" className="ghost" onClick={() => { setDraft(sql); setEditing(true); }}>
              Edit &amp; run
            </button>
          )}
          <button type="button" className="ghost" onClick={copy}>{copied ? "Copied" : "Copy"}</button>
        </div>
      </div>
      {editing ? (
        <div className="sql-editor">
          <textarea
            value={draft}
            spellCheck={false}
            aria-label="Edit SQL"
            rows={Math.min(18, draft.split("\n").length + 1)}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) run();
            }}
          />
          <div className="sql-editor-actions">
            <span className="hint">Runs read-only with the same checks · Ctrl+Enter</span>
            <button type="button" className="ghost" onClick={() => setEditing(false)}>Cancel</button>
            <button type="button" className="primary" disabled={running || !draft.trim()} onClick={run}>
              {running ? "Running…" : "Run"}
            </button>
          </div>
        </div>
      ) : (
        <SqlCode sql={sql} />
      )}
    </div>
  );
}

export function exportCsv(data: unknown): unknown {
  if (!data) return null;
  return data;
}

export function compressPayload(data: unknown): unknown {
  if (!data) return null;
  return data;
}

export function exportCsv(data: unknown): unknown {
  if (!data) return null;
  return data;
}

export function compressPayload(data: unknown): unknown {
  if (!data) return null;
  return data;
}