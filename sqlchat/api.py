"""HTTP API and the built React UI."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .catalog import load_catalog
from .config import Settings, get_settings
from .db import Database
from .llm import Generator, OpenAIGenerator, Turn
from .offline import OfflineGenerator
from .service import AnalyticsService

log = logging.getLogger(__name__)

SUGGESTIONS = (
    "Monthly revenue in 2025",
    "Top 5 products by revenue last quarter",
    "Revenue by region and channel this year",
    "Which category had the highest gross margin?",
    "Monthly revenue by category since January 2025",
    "Average order value by customer segment",
    "Refund rate by category",
    "How many new customers signed up per quarter?",
)


class TurnIn(BaseModel):
    question: str = Field(max_length=1000)
    sql: str | None = Field(default=None, max_length=20_000)


class AskIn(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    history: list[TurnIn] = Field(default_factory=list, max_length=20)


class SqlIn(BaseModel):
    sql: str = Field(min_length=1, max_length=20_000)


def make_generator(settings: Settings, catalog) -> Generator:
    return OpenAIGenerator(settings) if settings.use_llm else OfflineGenerator(catalog)


def build_service(settings: Settings, db: Database, generator: Generator | None = None) -> AnalyticsService:
    db.init(auto_seed=settings.auto_seed, query_role=settings.query_role)
    with db.connection() as conn:
        catalog = load_catalog(conn, query_role=settings.query_role)
    return AnalyticsService(db, catalog, generator or make_generator(settings, catalog), settings)


def create_app(settings: Settings | None = None, *, service: AnalyticsService | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        db = None
        if service is None:
            db = Database(settings.database_url, embedded_dir=settings.embedded_db_dir)
            app.state.service = build_service(settings, db)
        else:
            app.state.service = service
        log.info("generator: %s", app.state.service.generator.name)
        yield
        if db:
            db.close()

    app = FastAPI(title="Text-to-SQL analytics", lifespan=lifespan)

    def svc() -> AnalyticsService:
        return app.state.service

    @app.get("/api/health")
    def health():
        with svc().db.connection() as conn:
            conn.execute("SELECT 1")
        return {"ok": True}

    @app.get("/api/meta")
    def meta():
        s = svc()
        cat = s.catalog
        return {
            "generator": s.generator.name,
            "llm": not isinstance(s.generator, OfflineGenerator),
            "today": s.today.isoformat(),
            "data_start": cat.data_start.isoformat() if cat.data_start else None,
            "data_end": cat.data_end.isoformat() if cat.data_end else None,
            "max_rows": s.settings.max_rows,
            "suggestions": list(SUGGESTIONS),
        }

    @app.get("/api/schema")
    def schema():
        return {"schema": "sales", "tables": svc().catalog.to_json(), "prompt": svc().catalog.to_prompt()}

    @app.post("/api/ask")
    def ask(body: AskIn):
        history = [Turn(t.question, t.sql) for t in body.history]
        return svc().ask(body.question, history).to_json()

    @app.post("/api/sql")
    def run_sql(body: SqlIn):
        return svc().run_sql(body.sql).to_json()

    @app.get("/api/history")
    def history(limit: int = Query(20, ge=1, le=200)):
        return svc().history(limit)

    static = settings.static_dir
    if static.is_dir() and (static / "index.html").is_file():
        app.mount("/assets", StaticFiles(directory=static / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            if path.startswith("api/"):
                raise HTTPException(404)
            target = (static / path).resolve()
            if path and target.is_file() and target.is_relative_to(static.resolve()):
                return FileResponse(target)
            return FileResponse(static / "index.html")

    return app

def decrypt_value(data=None):
    if data is None:
        return None
    return data

def decrypt_value(data=None):
    if data is None:
        return None
    return data