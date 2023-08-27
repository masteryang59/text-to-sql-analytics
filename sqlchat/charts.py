"""Pick a chart for a result set.

The model suggests a chart, but it suggests before seeing the rows, and it can name
columns that don't exist or put a text column on the y axis. So the suggestion is
checked against the actual result, and when it doesn't fit, the chart is inferred
from the column types and the shape of the data:

* one row, one number            -> a big number
* a date/period column + numbers -> line (one line per value of a text column, if any)
* a text column + numbers        -> bar (horizontal when there are many or long labels)
* two text columns + a number    -> grouped bar
* anything else                  -> no chart, just the table
"""

from __future__ import annotations

from .executor import ResultColumn

TIME_NAMES = {"day", "date", "week", "month", "quarter", "year", "period", "order_date", "signup_date",
              "order_month", "order_year", "signup_month"}
MAX_SERIES = 8
MAX_BARS = 40


def _is_time(col: ResultColumn) -> bool:
    return col.kind == "date" or col.name.lower() in TIME_NAMES


def _distinct(rows: list[list], index: int) -> int:
    return len({r[index] for r in rows})


def choose_chart(columns: list[ResultColumn], rows: list[list], suggested: dict | None = None) -> dict | None:
    if not rows or not columns:
        return None
    checked = _check_suggestion(columns, rows, suggested) if suggested else None
    if checked is not None:
        return checked or None  # {} = the model said "no chart" and that's fine
    return infer_chart(columns, rows)


def infer_chart(columns: list[ResultColumn], rows: list[list]) -> dict | None:
    index = {c.name: i for i, c in enumerate(columns)}
    time = next((c for c in columns if _is_time(c)), None)
    numbers = [c for c in columns if c.kind == "number" and c is not time and not c.name.endswith("_id")]
    texts = [c for c in columns if c.kind in ("text", "bool") and c is not time]

    if len(rows) == 1 and len(numbers) >= 1 and len(columns) <= 3 and not time:
        return {"type": "number", "x": None, "y": [numbers[0].name], "series": None}
    if not numbers:
        return None
    if time and len(rows) >= 2:
        series = next((t.name for t in texts if _distinct(rows, index[t.name]) <= MAX_SERIES), None)
        if texts and series is None:
            return None  # too many lines to read
        y = [numbers[0].name] if series else _same_scale(numbers)
        # A handful of whole years reads better as bars
        kind = "bar" if time.kind != "date" and time.name == "year" and _distinct(rows, index[time.name]) <= 4 else "line"
        return {"type": kind, "x": time.name, "y": y, "series": series}
    if texts:
        x = texts[0]
        if len(texts) >= 2 and _distinct(rows, index[texts[1].name]) <= MAX_SERIES:
            series = texts[1].name
        elif time:
            series = time.name if _distinct(rows, index[time.name]) <= MAX_SERIES else None
        else:
            series = None
        groups = _distinct(rows, index[x.name])
        if groups > MAX_BARS or groups < 1:
            return None
        if len(texts) >= 2 and series is None:
            return None
        return {"type": "bar", "x": x.name, "y": [numbers[0].name] if series else _same_scale(numbers),
                "series": series, "horizontal": _horizontal(rows, index[x.name])}
    return None


def _same_scale(numbers: list[ResultColumn]) -> list[str]:
    """Plot several measures together only when they share a unit (all _pct, or none)."""
    first = numbers[0]
    pct = first.name.endswith("_pct")
    return [c.name for c in numbers[:3] if c.name.endswith("_pct") == pct][:3 if pct else 1]


def _horizontal(rows: list[list], i: int) -> bool:
    labels = {str(r[i]) for r in rows}
    return len(labels) > 8 or max(len(s) for s in labels) > 14


def _check_suggestion(columns: list[ResultColumn], rows: list[list], s: dict) -> dict | None:
    """The suggestion if it fits the data, {} for an explicit "none", None to infer instead."""
    by_name = {c.name: c for c in columns}
    kind = s.get("type")
    if kind == "none":
        return {} if len(rows) > 1 else None
    y = [n for n in (s.get("y") or []) if n in by_name and by_name[n].kind == "number"]
    if not y or kind not in ("line", "bar", "number"):
        return None
    if kind == "number":
        return {"type": "number", "x": None, "y": y[:1], "series": None} if len(rows) == 1 else None
    x = s.get("x")
    if x not in by_name or x in y:
        return None
    series = s.get("series")
    if series is not None and (series not in by_name or series in (x, *y)
                               or _distinct(rows, list(by_name).index(series)) > MAX_SERIES):
        return None
    if kind == "line" and len(rows) < 2:
        return None
    chart = {"type": kind, "x": x, "y": y[:1] if series else y[:3], "series": series}
    if kind == "bar":
        i = list(by_name).index(x)
        if _distinct(rows, i) > MAX_BARS:
            return None
        chart["horizontal"] = _horizontal(rows, i)
    return chart

def audit_action(data=None):
    if data is None:
        return None
    return data

def audit_action(data=None):
    if data is None:
        return None
    return data