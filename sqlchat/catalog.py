"""What the model is told about the database, read from Postgres itself.

Tables, columns, types, keys and comments come from the system catalogs, limited to
what the query role may SELECT. Columns it can't read (the customers' email and phone)
are left out of the prompt and listed as `hidden`, so the validator can refuse them
with a clear message instead of a permission error. Short text columns get their
distinct values listed, because the model can't guess that a status is spelled
'completed' rather than 'Complete'.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import psycopg
from psycopg import sql

SCHEMA = "sales"
# Text columns with at most this many distinct values get them listed in the prompt
MAX_LISTED_VALUES = 12


@dataclass
class ColumnInfo:
    name: str
    type: str
    nullable: bool
    comment: str | None = None
    primary_key: bool = False
    references: str | None = None  # "table.column"
    values: list[str] | None = None


@dataclass
class TableInfo:
    name: str
    comment: str | None
    row_count: int
    columns: list[ColumnInfo]
    hidden: list[str] = field(default_factory=list)

    def column(self, name: str) -> ColumnInfo | None:
        return next((c for c in self.columns if c.name == name), None)


@dataclass
class Catalog:
    tables: dict[str, TableInfo]
    data_start: date | None
    data_end: date | None
    # Values of the dimension columns, for the offline parser: "region" -> ["Europe", ...]
    dimension_values: dict[str, list[str]] = field(default_factory=dict)

    @property
    def table_names(self) -> set[str]:
        return set(self.tables)

    @property
    def hidden_columns(self) -> dict[str, set[str]]:
        return {t.name: set(t.hidden) for t in self.tables.values() if t.hidden}

    def to_prompt(self) -> str:
        """Compact DDL-like text: one line per column with its key, comment and values."""
        out = []
        for t in self.tables.values():
            out.append(f"TABLE {SCHEMA}.{t.name}  -- {t.comment or ''} (~{t.row_count:,} rows)".rstrip())
            for c in t.columns:
                parts = [f"  {c.name} {c.type}"]
                if c.primary_key:
                    parts.append("PRIMARY KEY")
                if c.references:
                    table, _, col = c.references.partition(".")
                    parts.append(f"REFERENCES {SCHEMA}.{table}({col})")
                if c.nullable and not c.primary_key:
                    parts.append("NULL")
                notes = []
                if c.comment:
                    notes.append(c.comment)
                if c.values:
                    notes.append("values: " + ", ".join(f"'{v}'" for v in c.values))
                line = " ".join(parts)
                out.append(f"{line}  -- {' '.join(notes)}" if notes else line)
            out.append("")
        return "\n".join(out).rstrip()

    def to_json(self) -> list[dict]:
        return [
            {
                "name": t.name,
                "comment": t.comment,
                "row_count": t.row_count,
                "hidden": t.hidden,
                "columns": [
                    {"name": c.name, "type": c.type, "comment": c.comment, "primary_key": c.primary_key,
                     "references": c.references, "values": c.values}
                    for c in t.columns
                ],
            }
            for t in self.tables.values()
        ]


_COLUMNS = """
SELECT c.relname AS table_name,
       obj_description(c.oid, 'pg_class') AS table_comment,
       greatest(c.reltuples, 0)::bigint AS row_estimate,
       a.attname AS column_name,
       format_type(a.atttypid, a.atttypmod) AS data_type,
       NOT a.attnotnull AS nullable,
       col_description(c.oid, a.attnum) AS column_comment,
       CASE WHEN %(role)s = '' THEN true
            ELSE has_column_privilege(%(role)s, c.oid, a.attnum, 'SELECT') END AS visible,
       CASE WHEN %(role)s = '' THEN true
            ELSE has_table_privilege(%(role)s, c.oid, 'SELECT')
                 OR has_any_column_privilege(%(role)s, c.oid, 'SELECT') END AS table_visible
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum > 0 AND NOT a.attisdropped
WHERE n.nspname = %(schema)s AND c.relkind IN ('r', 'v', 'm', 'p')
ORDER BY c.oid, a.attnum
"""

_KEYS = """
SELECT con.contype, src.relname AS table_name, sa.attname AS column_name,
       dst.relname AS ref_table, da.attname AS ref_column
FROM pg_constraint con
JOIN pg_class src ON src.oid = con.conrelid
JOIN pg_namespace n ON n.oid = src.relnamespace
JOIN LATERAL unnest(con.conkey) WITH ORDINALITY AS k(attnum, ord) ON true
JOIN pg_attribute sa ON sa.attrelid = src.oid AND sa.attnum = k.attnum
LEFT JOIN pg_class dst ON dst.oid = con.confrelid
LEFT JOIN pg_attribute da ON da.attrelid = con.confrelid AND da.attnum = con.confkey[k.ord]
WHERE n.nspname = %(schema)s AND con.contype IN ('p', 'f') AND array_length(con.conkey, 1) = 1
"""

# Columns whose values the offline parser matches in questions ("revenue in Europe")
DIMENSION_COLUMNS = {
    "category": ("categories", "name"),
    "region": ("regions", "name"),
    "product": ("products", "name"),
    "country": ("customers", "country"),
    "segment": ("customers", "segment"),
    "channel": ("orders", "channel"),
    "rep": ("sales_reps", "name"),
}


def load_catalog(conn: psycopg.Connection, *, query_role: str = "") -> Catalog:
    rows = conn.execute(_COLUMNS, {"role": query_role, "schema": SCHEMA}).fetchall()
    tables: dict[str, TableInfo] = {}
    for r in rows:
        if not r["table_visible"]:
            continue
        t = tables.setdefault(r["table_name"], TableInfo(r["table_name"], r["table_comment"], r["row_estimate"], []))
        if r["visible"]:
            t.columns.append(ColumnInfo(r["column_name"], r["data_type"], r["nullable"], r["column_comment"]))
        else:
            t.hidden.append(r["column_name"])

    for k in conn.execute(_KEYS, {"schema": SCHEMA}).fetchall():
        table = tables.get(k["table_name"])
        col = table and table.column(k["column_name"])
        if not col:
            continue
        if k["contype"] == "p":
            col.primary_key = True
        elif k["ref_table"] in tables:
            col.references = f"{k['ref_table']}.{k['ref_column']}"

    for t in tables.values():
        ident = sql.Identifier(SCHEMA, t.name)
        if t.row_count == 0:  # never analyzed
            t.row_count = conn.execute(sql.SQL("SELECT count(*) AS n FROM {}").format(ident)).fetchone()["n"]
        for c in t.columns:
            if c.type != "text" or c.primary_key:
                continue
            vals = conn.execute(
                sql.SQL("SELECT DISTINCT {c} AS v FROM {t} WHERE {c} IS NOT NULL ORDER BY 1 LIMIT %s").format(
                    c=sql.Identifier(c.name), t=ident),
                (MAX_LISTED_VALUES + 1,),
            ).fetchall()
            if len(vals) <= MAX_LISTED_VALUES:
                c.values = [v["v"] for v in vals]

    start = end = None
    if "orders" in tables:
        span = conn.execute(f"SELECT min(order_date) AS s, max(order_date) AS e FROM {SCHEMA}.orders").fetchone()
        start, end = span["s"], span["e"]

    dims = {}
    for dim, (table, column) in DIMENSION_COLUMNS.items():
        if table in tables and tables[table].column(column):
            q = sql.SQL("SELECT DISTINCT {c} AS v FROM {t} WHERE {c} IS NOT NULL ORDER BY 1 LIMIT 500").format(
                c=sql.Identifier(column), t=sql.Identifier(SCHEMA, table))
            dims[dim] = [r["v"] for r in conn.execute(q).fetchall()]
    return Catalog(tables, start, end, dims)

def mask_pii(data=None):
    if data is None:
        return None
    return data