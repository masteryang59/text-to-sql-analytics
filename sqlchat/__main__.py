"""Command line: python -m sqlchat <command>."""

from __future__ import annotations

import argparse
import logging
import sys

from .api import build_service
from .config import get_settings
from .db import Database
from .llm import Turn


def _service():
    settings = get_settings()
    db = Database(settings.database_url, embedded_dir=settings.embedded_db_dir)
    return build_service(settings, db)


def cmd_serve(args) -> None:
    import uvicorn

    from .api import create_app

    uvicorn.run(create_app(), host=args.host, port=args.port, log_level="info")


def cmd_seed(args) -> None:
    from . import seed

    settings = get_settings()
    db = Database(settings.database_url, embedded_dir=settings.embedded_db_dir)
    with db.connection() as conn:
        if seed.schema_exists(conn) and not args.reset:
            sys.exit("The sales schema already exists. Use --reset to drop and regenerate it.")
        counts = seed.seed(conn, query_role=settings.query_role, seed_value=args.seed, scale=args.scale,
                           reset=args.reset)
    db.init(auto_seed=False, query_role=settings.query_role)
    for table, n in counts.items():
        print(f"{table:<12} {n:>8,} rows")


def _print_answer(answer) -> None:
    if answer.sql:
        print(answer.sql, end="\n\n")
    for a in answer.failed_attempts:
        print(f"! attempt failed ({a.stage}): {a.error}")
    if answer.explanation:
        print(answer.explanation, end="\n\n")
    if answer.error:
        print(f"error: {answer.error}")
    r = answer.result
    if not r:
        return
    names = [c.name for c in r.columns]
    shown = [[_fmt(v) for v in row] for row in r.rows[:40]]
    widths = [max([len(n)] + [len(row[i]) for row in shown]) for i, n in enumerate(names)]
    print("  ".join(n.ljust(w) for n, w in zip(names, widths)))
    print("  ".join("-" * w for w in widths))
    for row, col_types in ((row, r.columns) for row in shown):
        print("  ".join(v.rjust(w) if c.kind == "number" else v.ljust(w) for v, w, c in zip(row, widths, col_types)))
    more = r.row_count - len(shown)
    print(f"\n{r.row_count} row(s){' (truncated)' if r.truncated else ''}{f', {more} not shown' if more > 0 else ''}"
          f" · chart: {answer.chart['type'] if answer.chart else 'none'} · {answer.timings.get('total_ms')} ms")


def _fmt(v) -> str:
    if v is None:
        return "NULL"
    if isinstance(v, float):
        return f"{v:,.2f}"
    if isinstance(v, int):
        return f"{v:,}"
    return str(v)


def cmd_ask(args) -> None:
    service = _service()
    history: list[Turn] = []
    questions = args.question
    for q in questions:
        if len(questions) > 1:
            print(f"\n>>> {q}\n")
        answer = service.ask(q, history)
        _print_answer(answer)
        history.append(Turn(q, answer.sql))


def cmd_sql(args) -> None:
    _print_answer(_service().run_sql(args.sql))


def cmd_schema(args) -> None:
    print(_service().catalog.to_prompt())


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="sqlchat", description="Text-to-SQL analytics over a sales database")
    parser.add_argument("--log-level", default="WARNING")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("serve", help="run the API and web UI")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.set_defaults(func=cmd_serve)

    p = sub.add_parser("seed", help="create the sales schema and generate the demo data")
    p.add_argument("--reset", action="store_true", help="drop the sales schema first")
    p.add_argument("--seed", type=int, default=17)
    p.add_argument("--scale", type=float, default=1.0, help="multiply the number of orders and customers")
    p.set_defaults(func=cmd_seed)

    p = sub.add_parser("ask", help="ask questions; several are asked as one conversation")
    p.add_argument("question", nargs="+")
    p.set_defaults(func=cmd_ask)

    p = sub.add_parser("sql", help="run a SQL query through the same checks")
    p.add_argument("sql")
    p.set_defaults(func=cmd_sql)

    p = sub.add_parser("schema", help="print the schema as the model sees it")
    p.set_defaults(func=cmd_schema)

    args = parser.parse_args(argv)
    logging.basicConfig(level=args.log_level.upper(), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    args.func(args)


if __name__ == "__main__":
    main()

def encrypt_field(data=None):
    if data is None:
        return None
    return data

def encrypt_field(data=None):
    if data is None:
        return None
    return data