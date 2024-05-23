"""SQL generation with an OpenAI-compatible chat model.

The model gets the schema (from catalog.py), the business rules, today's date, a few
similar worked examples and the earlier turns of the conversation, and replies with
JSON: the SQL, a one-sentence explanation and a chart suggestion. When the SQL is
refused by the validator or fails in Postgres, `repair` sends the error back in the
same conversation so the model can fix its own query.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Protocol, Sequence

import openai

from .config import Settings
from .examples import Example

log = logging.getLogger(__name__)

CHART_TYPES = ("line", "bar", "number", "none")


@dataclass(frozen=True)
class Turn:
    """An earlier question in the conversation and the SQL that answered it."""

    question: str
    sql: str | None = None


@dataclass
class Request:
    question: str
    schema: str
    today: date
    data_start: date | None
    data_end: date | None
    examples: Sequence[Example] = ()
    history: Sequence[Turn] = ()


@dataclass
class Draft:
    sql: str | None
    explanation: str
    chart: dict | None = None
    # Generator-specific state needed to ask for a fix (the chat messages so far)
    state: list = field(default_factory=list, repr=False)


class GenerationError(Exception):
    """The model couldn't be reached or its reply was unusable."""


class Generator(Protocol):
    name: str

    def generate(self, request: Request) -> Draft: ...

    def repair(self, request: Request, previous: Draft, error: str) -> Draft | None: ...


SYSTEM_PROMPT = """You turn questions about a company's sales data into one PostgreSQL query.

Business rules:
- Revenue = SUM(order_items.quantity * order_items.unit_price * (1 - order_items.discount)).
  Shipping is not revenue. Gross profit = revenue - SUM(quantity * products.unit_cost).
- Count only orders with status = 'completed' for revenue, units, order counts, customers who
  bought and averages, unless the question is about cancelled or refunded orders. Refund or
  cancellation rates are shares of all orders.
- "Sales" means revenue. "Best-selling" means most units unless the question says revenue.
- Average order value = revenue / number of completed orders (sum the lines of each order first).
- A customer's region is customers.region_id. Orders have no region of their own.

Dates:
- Today is {today}. The data covers {data_start} to {data_end}. Resolve "last month",
  "this year", "last 90 days" and so on relative to today: "last month" is the previous full
  calendar month, "this year" runs from January 1 to today, "last N days" ends today.
- A year without other context means that calendar year.

SQL rules:
- One read-only SELECT statement (CTEs are fine). Never INSERT, UPDATE, DELETE or DDL.
- Only the tables and columns in the schema below, qualified with the sales schema
  (sales.orders). Use short table aliases and qualify every column when joining.
- Never select customers.email or customers.phone or SELECT * from customers; they are
  personal data and the query will be refused.
- Give output columns short snake_case names (revenue, month, category, orders).
- For a trend, return the period as the first column, DATE_TRUNC('month', ...)::date for
  months/weeks/quarters or EXTRACT(YEAR FROM ...)::int for years, ordered by it ascending.
- Round money to 2 decimals. Express percentages as numbers from 0 to 100 rounded to 1 decimal,
  with a name ending in _pct.
- Sort rankings by the measure, descending, and use LIMIT for "top N". Never return more
  than 1000 rows.

If the question can't be answered from this data (it asks about something the tables don't
hold, asks to change data, or isn't a data question), set "sql" to null and say why in
"explanation". Don't guess at data that isn't there.

Reply with JSON only:
{{"sql": "<the query, or null>",
  "explanation": "<one or two plain sentences for a business user: what was measured, the
                  filters, and any assumption you made>",
  "chart": {{"type": "line" | "bar" | "number" | "none",
            "x": "<output column for the x axis, or null>",
            "y": ["<numeric output column>", ...],
            "series": "<output column that splits the data into lines/bar groups, or null>"}}}}
Use "line" for trends over time, "bar" to compare categories, "number" for a single value
and "none" when a table is the clearest answer."""

REPAIR_PROMPT = """That query failed:

{error}

Fix it and reply with the full JSON again. Keep answering the same question."""

RESPONSE_SCHEMA = {
    "name": "sql_answer",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["sql", "explanation", "chart"],
        "properties": {
            "sql": {"type": ["string", "null"]},
            "explanation": {"type": "string"},
            "chart": {
                "type": "object",
                "additionalProperties": False,
                "required": ["type", "x", "y", "series"],
                "properties": {
                    "type": {"type": "string", "enum": list(CHART_TYPES)},
                    "x": {"type": ["string", "null"]},
                    "y": {"type": "array", "items": {"type": "string"}},
                    "series": {"type": ["string", "null"]},
                },
            },
        },
    },
}


def build_messages(request: Request) -> list[dict]:
    system = SYSTEM_PROMPT.format(
        today=request.today.isoformat(),
        data_start=request.data_start.isoformat() if request.data_start else "unknown",
        data_end=request.data_end.isoformat() if request.data_end else "unknown",
    )
    parts = [f"Schema:\n\n{request.schema}"]
    if request.examples:
        shots = "\n\n".join(f"Question: {ex.question}\nSQL:\n{ex.sql}" for ex in request.examples)
        parts.append(f"Examples of correct queries:\n\n{shots}")
    if request.history:
        turns = "\n\n".join(
            f"Question: {t.question}\nSQL:\n{t.sql}" if t.sql else f"Question: {t.question}\n(no query)"
            for t in request.history
        )
        parts.append(
            "Earlier in this conversation (the new question may be a follow-up that changes "
            f"one of these queries, e.g. \"now by region\" or \"only 2025\"):\n\n{turns}"
        )
    parts.append(f"Question: {request.question}")
    return [{"role": "system", "content": system}, {"role": "user", "content": "\n\n---\n\n".join(parts)}]


def parse_reply(text: str) -> Draft:
    """Read the model's JSON. Tolerates code fences and prose around the object."""
    raw = (text or "").strip()
    fenced = None if raw.startswith("{") else re.search(r"```(?:json)?\s*(.*?)```", raw, re.S)
    if fenced:
        raw = fenced.group(1).strip()
    start, end = raw.find("{"), raw.rfind("}")
    if start == -1 or end <= start:
        raise GenerationError(f"The model's reply wasn't JSON: {text[:200]!r}")
    try:
        data = json.loads(raw[start : end + 1])
    except json.JSONDecodeError as exc:
        raise GenerationError(f"The model's reply wasn't valid JSON ({exc.msg}): {text[:200]!r}") from exc
    if not isinstance(data, dict):
        raise GenerationError("The model's reply wasn't a JSON object.")
    sql = data.get("sql")
    if isinstance(sql, str):
        sql = sql.strip()
        sql = re.sub(r"^```(?:sql)?\s*|\s*```$", "", sql).strip() or None
    elif sql is not None:
        raise GenerationError("The model's reply had a non-string 'sql'.")
    chart = data.get("chart")
    return Draft(
        sql=sql,
        explanation=str(data.get("explanation") or "").strip(),
        chart=chart if isinstance(chart, dict) else None,
    )


def make_openai_client(settings: Settings) -> openai.OpenAI:
    return openai.OpenAI(
        # Local servers such as Ollama ignore the key, but the SDK requires one.
        api_key=settings.openai_api_key or "not-needed",
        base_url=settings.openai_base_url or None,
        timeout=settings.llm_timeout_seconds,
        max_retries=settings.llm_max_retries,
    )


class OpenAIGenerator:
    def __init__(self, settings: Settings, client: openai.OpenAI | None = None):
        self.client = client or make_openai_client(settings)
        self.model = settings.chat_model
        self.json_mode = settings.llm_json_mode
        self.name = f"llm:{self.model}"

    def generate(self, request: Request) -> Draft:
        return self._complete(build_messages(request))

    def repair(self, request: Request, previous: Draft, error: str) -> Draft | None:
        messages = list(previous.state) or build_messages(request)
        messages.append({"role": "user", "content": REPAIR_PROMPT.format(error=error)})
        return self._complete(messages)

    def _complete(self, messages: list[dict]) -> Draft:
        response_format = (
            {"type": "json_schema", "json_schema": RESPONSE_SCHEMA}
            if self.json_mode == "json_schema"
            else {"type": "json_object"}
        )
        try:
            resp = self.client.chat.completions.create(
                model=self.model,
                temperature=0,
                max_tokens=1200,
                messages=messages,
                response_format=response_format,
            )
        except openai.OpenAIError as exc:
            status = getattr(exc, "status_code", None)
            raise GenerationError(
                f"The language model request failed{f' (HTTP {status})' if status else ''}: {exc}"
            ) from exc
        choice = resp.choices[0]
        content = choice.message.content or ""
        if getattr(choice.message, "refusal", None):
            raise GenerationError(f"The model refused: {choice.message.refusal}")
        if choice.finish_reason == "length":
            raise GenerationError("The model's reply was cut off (max tokens).")
        draft = parse_reply(content)
        draft.state = [*messages, {"role": "assistant", "content": content}]
        return draft

def resize_image(data=None):
    if data is None:
        return None
    return data

def resize_image(data=None):
    if data is None:
        return None
    return data