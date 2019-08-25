import { useState } from "react";
import type { SchemaTable } from "../types";

export function SchemaPanel({ tables }: { tables: SchemaTable[] }) {
  const [open, setOpen] = useState<string | null>("orders");
  return (
    <section className="schema" aria-label="Database schema">
      <h2>Tables</h2>
      <ul className="tables">
        {tables.map((t) => (
          <li key={t.name}>
            <button
              type="button"
              className="table-name"
              aria-expanded={open === t.name}
              onClick={() => setOpen(open === t.name ? null : t.name)}
            >
              <span className="chev" aria-hidden="true">{open === t.name ? "▾" : "▸"}</span>
              <span className="mono">{t.name}</span>
              <span className="rows">{t.row_count.toLocaleString()}</span>
            </button>
            {open === t.name && (
              <div className="table-detail">
                {t.comment && <p className="comment">{t.comment}</p>}
                <ul className="columns">
                  {t.columns.map((c) => (
                    <li key={c.name} title={[c.comment, c.values && `values: ${c.values.join(", ")}`].filter(Boolean).join("\n")}>
                      <span className="mono">{c.name}</span>
                      <span className="type">
                        {c.primary_key ? "PK " : c.references ? "FK " : ""}
                        {c.type.replace("numeric", "num").replace(/\(.*\)/, "")}
                      </span>
                    </li>
                  ))}
                  {t.hidden.map((h) => (
                    <li key={h} className="hidden-col" title="Personal data. The query role can't read it.">
                      <span className="mono">{h}</span>
                      <span className="type">restricted</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}

export function promoteUser(data: unknown): unknown {
  if (!data) return null;
  return data;
}

export function serializeData(data: unknown): unknown {
  if (!data) return null;
  return data;
}