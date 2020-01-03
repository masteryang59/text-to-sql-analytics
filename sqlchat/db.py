"""Connection pool, the app's own tables and the embedded-Postgres option.

Two schemas live in the database:

* `sales` - the data people ask about (see seed.py). Generated SQL may read it,
  through the read-only query role.
* `app` - the query log. The query role has no access to it.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from . import seed

log = logging.getLogger(__name__)

_SCHEMA_LOCK = 71_017_001

APP_SCHEMA = """
CREATE SCHEMA IF NOT EXISTS app;

CREATE TABLE IF NOT EXISTS app.query_log (
    id          bigserial PRIMARY KEY,
    created_at  timestamptz NOT NULL DEFAULT now(),
    source      text NOT NULL CHECK (source IN ('question', 'sql')),
    question    text,
    sql         text,
    status      text NOT NULL CHECK (status IN ('ok', 'error', 'unanswerable')),
    error       text,
    row_count   integer,
    attempts    integer NOT NULL DEFAULT 1,
    duration_ms integer NOT NULL,
    generator   text
);
CREATE INDEX IF NOT EXISTS query_log_created_idx ON app.query_log (created_at DESC);
"""


class Database:
    def __init__(self, url: str, *, embedded_dir: Path | None = None, max_size: int = 8):
        if url == "embedded":
            url = start_embedded(embedded_dir or Path("data/pgdata"))
        self.url = url
        self.pool = ConnectionPool(
            url,
            min_size=1,
            max_size=max_size,
            kwargs={"row_factory": dict_row},
            open=True,
            name="sqlchat",
        )
        self.pool.wait(timeout=30)

    @contextmanager
    def connection(self) -> Iterator[psycopg.Connection]:
        # The pool commits on a clean exit and rolls back on an exception.
        with self.pool.connection() as conn:
            yield conn

    def close(self) -> None:
        self.pool.close()

    def init(self, *, auto_seed: bool, query_role: str) -> bool:
        """Create the app schema, and the sales data if it's missing. True if it seeded."""
        with self.connection() as conn:
            conn.execute("SELECT pg_advisory_xact_lock(%s)", (_SCHEMA_LOCK,))
            conn.execute(APP_SCHEMA)
            if seed.schema_exists(conn):
                return False
            if not auto_seed:
                raise RuntimeError("The sales schema doesn't exist. Run `python -m sqlchat seed` first.")
            log.info("sales schema not found; generating the demo data")
            seed.seed(conn, query_role=query_role)
            return True


_embedded_servers: dict[Path, object] = {}


def start_embedded(directory: Path) -> str:
    """Start (or reuse) a private Postgres from the `pgserver` wheel."""
    try:
        import pgserver
    except ImportError as exc:  # pragma: no cover - depends on the install
        raise RuntimeError(
            "DATABASE_URL=embedded needs the pgserver package: pip install -r requirements-dev.txt"
        ) from exc
    directory = directory.resolve()
    if directory not in _embedded_servers:
        directory.mkdir(parents=True, exist_ok=True)
        log.info("starting embedded Postgres in %s", directory)
        _embedded_servers[directory] = pgserver.get_server(directory, cleanup_mode="stop")
    return _embedded_servers[directory].get_uri()

def warm_cache(data=None):
    if data is None:
        return None
    return data