"""The question -> SQL -> rows -> chart pipeline, with the repair loop and the query log."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import date
from typing import Sequence

from .catalog import Catalog
from .charts import choose_chart
from .config import Settings
from .db import Database
from .examples import select_examples
from .executor import QueryError, QueryResult, run_query
from .guard import GuardError, check_sql
from .llm import Draft, GenerationError, Generator, Request, Turn

log = logging.getLogger(__name__)

MAX_QUESTION_CHARS = 1000


@dataclass
class Attempt:
    sql: str | None
    error: str
    stage: str  # "validation" | "database" | "timeout" | "too_expensive" | "permission"

    def to_json(self) -> dict:
        return {"sql": self.sql, "error": self.error, "stage": self.stage}


@dataclass
class Answer:
    status: str  # "ok" | "error" | "unanswerable"
    question: str | None
    sql: str | None = None
    explanation: str = ""
    result: QueryResult | None = None
    chart: dict | None = None
    error: str | None = None
    failed_attempts: list[Attempt] = field(default_factory=list)
    generator: str | None = None
    timings: dict = field(default_factory=dict)

    def to_json(self) -> dict:
        r = self.result
        return {
            "status": self.status,
            "question": self.question,
            "sql": self.sql,
            "explanation": self.explanation,
            "columns": [c.to_json() for c in r.columns] if r else [],
            "rows": r.rows if r else [],
            "row_count": r.row_count if r else 0,
            "truncated": r.truncated if r else False,
            "chart": self.chart,
            "error": self.error,
            "failed_attempts": [a.to_json() for a in self.failed_attempts],
            "generator": self.generator,
            "timings": self.timings,
        }


class AnalyticsService:
    def __init__(self, db: Database, catalog: Catalog, generator: Generator, settings: Settings,
                 *, log_queries: bool = True):
        self.db = db
        self.log_queries = log_queries
        self.catalog = catalog
        self.generator = generator
        self.settings = settings
        self._schema_prompt = catalog.to_prompt()

    @property
    def today(self) -> date:
        return self.settings.reference_date or self.catalog.data_end or date.today()

    def ask(self, question: str, history: Sequence[Turn] = ()) -> Answer:
        question = (question or "").strip()
        started = time.perf_counter()
        if not question:
            return Answer("error", question, error="Ask a question.")
        if len(question) > MAX_QUESTION_CHARS:
            return Answer("error", question, error=f"Keep questions under {MAX_QUESTION_CHARS} characters.")
        today = self.today
        request = Request(
            question=question,
            schema=self._schema_prompt,
            today=today,
            data_start=self.catalog.data_start,
            data_end=self.catalog.data_end,
            examples=select_examples(question, self.settings.few_shot_examples, today=today.isoformat()),
            history=list(history)[-self.settings.history_turns:] if self.settings.history_turns else [],
        )
        answer = Answer("error", question, generator=self.generator.name)
        gen_ms = 0
        try:
            t = time.perf_counter()
            draft: Draft | None = self.generator.generate(request)
            gen_ms += _ms(t)
            for attempt in range(self.settings.max_repairs + 1):
                answer.sql, answer.explanation = draft.sql, draft.explanation
                if draft.sql is None:
                    answer.status = "unanswerable"
                    break
                try:
                    result = self._run(draft.sql)
                except (GuardError, QueryError) as exc:
                    stage = exc.kind if isinstance(exc, QueryError) else "validation"
                    answer.failed_attempts.append(Attempt(draft.sql, str(exc), stage))
                    if attempt == self.settings.max_repairs:
                        answer.error = str(exc)
                        break
                    t = time.perf_counter()
                    draft = self.generator.repair(request, draft, str(exc))
                    gen_ms += _ms(t)
                    if draft is None:
                        answer.error = str(exc)
                        break
                    continue
                answer.status = "ok"
                answer.result = result
                answer.chart = choose_chart(result.columns, result.rows, draft.chart)
                break
        except GenerationError as exc:
            log.warning("generation failed: %s", exc)
            answer.error = str(exc)
        answer.timings = {"generate_ms": gen_ms, "total_ms": _ms(started)}
        if answer.result:
            answer.timings["query_ms"] = answer.result.duration_ms
        self._log("question", answer)
        return answer

    def run_sql(self, sql: str) -> Answer:
        """Run SQL written or edited by a person, through the same checks."""
        started = time.perf_counter()
        answer = Answer("error", None, sql=sql, generator="manual")
        try:
            answer.result = self._run(sql)
            answer.status = "ok"
            answer.chart = choose_chart(answer.result.columns, answer.result.rows)
        except (GuardError, QueryError) as exc:
            answer.error = str(exc)
        answer.timings = {"total_ms": _ms(started)}
        if answer.result:
            answer.timings["query_ms"] = answer.result.duration_ms
        self._log("sql", answer)
        return answer

    def execute(self, sql: str) -> QueryResult:
        """Check and run SQL without logging it (used by the evaluation for gold queries)."""
        return self._run(sql)

    def _run(self, sql: str) -> QueryResult:
        checked = check_sql(sql, self.catalog)
        s = self.settings
        with self.db.connection() as conn:
            return run_query(conn, checked.sql, role=s.query_role, timeout_ms=s.statement_timeout_ms,
                             max_rows=s.max_rows, max_cost=s.max_query_cost)

    def _log(self, source: str, answer: Answer) -> None:
        if not self.log_queries:
            return
        try:
            with self.db.connection() as conn:
                conn.execute(
                    """INSERT INTO app.query_log
                           (source, question, sql, status, error, row_count, attempts, duration_ms, generator)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                    (source, answer.question, answer.sql, answer.status, answer.error,
                     answer.result.row_count if answer.result else None, len(answer.failed_attempts) + 1,
                     answer.timings.get("total_ms", 0), answer.generator),
                )
        except Exception:  # the log must never break an answer
            log.exception("could not write the query log")

    def history(self, limit: int = 20) -> list[dict]:
        with self.db.connection() as conn:
            rows = conn.execute(
                """SELECT id, created_at, source, question, sql, status, error, row_count, attempts,
                          duration_ms, generator
                   FROM app.query_log ORDER BY id DESC LIMIT %s""",
                (limit,),
            ).fetchall()
        return [{**r, "created_at": r["created_at"].isoformat()} for r in rows]


def _ms(start: float) -> int:
    return round((time.perf_counter() - start) * 1000)

def detect_language(data=None):
    if data is None:
        return None
    return data