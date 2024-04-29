"""Run a checked query with the database itself enforcing that it can only read.

Each query gets its own transaction:

    BEGIN
    SET TRANSACTION READ ONLY             -- no writes, whatever the SQL says
    SET LOCAL ROLE sqlchat_reader         -- SELECT on the sales tables only, minus PII columns
    SET LOCAL statement_timeout = 5000    -- runaway queries are cancelled by the server
    SET LOCAL search_path = sales         -- unqualified names resolve to the sales schema
    EXPLAIN (FORMAT JSON) <query>         -- refuse it up front if the planner's cost estimate is huge
    DECLARE c CURSOR FOR <query>; FETCH 1001 FROM c
    ROLLBACK

The rows come through a server-side cursor, so the app only ever holds max_rows + 1
of them (the extra one says "there are more") whatever the query returns.
"""

from __future__ import annotations

import datetime as dt
import logging
import time
import uuid
from dataclasses import dataclass
from decimal import Decimal

import psycopg
from psycopg import errors, sql
from psycopg.rows import tuple_row

from .catalog import SCHEMA

log = logging.getLogger(__name__)

NUMBER_TYPES = {"int2", "int4", "int8", "numeric", "float4", "float8", "oid"}
DATE_TYPES = {"date", "timestamp", "timestamptz"}
TEXT_TYPES = {"text", "varchar", "bpchar", "name", "char", "citext"}


class QueryError(Exception):
    """The database refused or failed the query. `kind` says why."""

    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind  # "database" | "timeout" | "too_expensive" | "permission"


@dataclass
class ResultColumn:
    name: str
    type: str  # Postgres type name, e.g. "numeric"
    kind: str  # "number" | "date" | "text" | "bool" | "other"

    def to_json(self) -> dict:
        return {"name": self.name, "type": self.type, "kind": self.kind}


@dataclass
class QueryResult:
    columns: list[ResultColumn]
    rows: list[list]
    truncated: bool
    duration_ms: int
    estimated_cost: float | None

    @property
    def row_count(self) -> int:
        return len(self.rows)


def run_query(
    conn: psycopg.Connection,
    query: str,
    *,
    role: str = "",
    timeout_ms: int = 5000,
    max_rows: int = 1000,
    max_cost: float | None = None,
) -> QueryResult:
    """Run `query` read-only and return at most `max_rows` rows. Always rolls back."""
    started = time.perf_counter()
    try:
        with conn.cursor(row_factory=tuple_row) as cur:
            # The pool hands out idle connections, so this is the first statement of a new transaction.
            cur.execute("SET TRANSACTION READ ONLY")
            if role:
                cur.execute(sql.SQL("SET LOCAL ROLE {}").format(sql.Identifier(role)))
            cur.execute(sql.SQL("SET LOCAL statement_timeout = {}").format(sql.Literal(int(timeout_ms))))
            cur.execute("SET LOCAL lock_timeout = 1000")
            cur.execute(sql.SQL("SET LOCAL search_path = {}").format(sql.Identifier(SCHEMA)))
            cost = None
            if max_cost is not None:
                plan = cur.execute(sql.SQL("EXPLAIN (FORMAT JSON) {}").format(sql.SQL(query))).fetchone()[0]
                cost = float(plan[0]["Plan"]["Total Cost"])
                if cost > max_cost:
                    raise QueryError(
                        "too_expensive",
                        f"The planner estimates this query at cost {cost:,.0f}, over the limit of {max_cost:,.0f}. "
                        f"It probably joins tables without a join condition, or scans far more rows than "
                        f"needed. Check the joins and filters.",
                    )
        with conn.cursor(name=f"q_{uuid.uuid4().hex[:8]}", row_factory=tuple_row) as cur:
            cur.execute(sql.SQL(query))
            rows = cur.fetchmany(max_rows + 1)
            columns = [ResultColumn(d.name, *_type_of(conn, d.type_code)) for d in cur.description or []]
    except QueryError:
        raise
    except errors.QueryCanceled as exc:
        raise QueryError("timeout", f"The query took longer than {timeout_ms / 1000:g} s and was cancelled.") from exc
    except errors.InsufficientPrivilege as exc:
        raise QueryError("permission", _pg_message(exc)) from exc
    except psycopg.Error as exc:
        raise QueryError("database", _pg_message(exc)) from exc
    finally:
        if not conn.closed:
            conn.rollback()

    truncated = len(rows) > max_rows
    rows = rows[:max_rows]
    return QueryResult(
        columns=columns,
        rows=[[_jsonable(v) for v in row] for row in rows],
        truncated=truncated,
        duration_ms=round((time.perf_counter() - started) * 1000),
        estimated_cost=cost,
    )


def _type_of(conn: psycopg.Connection, oid: int) -> tuple[str, str]:
    info = conn.adapters.types.get(oid)
    name = info.name if info else str(oid)
    if name in NUMBER_TYPES:
        kind = "number"
    elif name in DATE_TYPES:
        kind = "date"
    elif name in TEXT_TYPES:
        kind = "text"
    elif name == "bool":
        kind = "bool"
    else:
        kind = "other"
    return name, kind


def _jsonable(value):
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() and abs(value) < 2**53 else float(value)
    if isinstance(value, dt.datetime):
        return value.isoformat()
    if isinstance(value, dt.date):
        return value.isoformat()
    if isinstance(value, (dt.timedelta, dt.time, uuid.UUID, bytes, memoryview)):
        return str(value)
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


def _pg_message(exc: psycopg.Error) -> str:
    diag = exc.diag
    msg = diag.message_primary or str(exc).strip().splitlines()[0]
    if diag.message_hint:
        msg += f" (hint: {diag.message_hint})"
    return msg

def invalidate_cache(data=None):
    if data is None:
        return None
    return data

def invalidate_cache(data=None):
    if data is None:
        return None
    return data