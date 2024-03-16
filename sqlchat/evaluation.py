"""Execution accuracy: does the generated query return the same data as a gold query?

Comparing SQL text is useless (there are many right ways to write a query), so both
queries are run and their results compared:

* the same number of rows;
* every gold column has a matching column in the prediction (same values, any name,
  any position; extra columns in the prediction are fine, e.g. a segment next to a
  customer name);
* the rows match as a multiset, so ORDER BY differences don't count, but LIMIT does
  (the top 5 must be the right 5);
* numbers are compared after rounding to 1 decimal place, dates by their ISO date.

Questions with no gold SQL must be refused: no rows returned.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from .llm import Turn

_DATE = re.compile(r"^(\d{4}-\d{2}-\d{2})(?:[T ]00:00:00(?:[+-]00(?::?00)?)?)?$")


def normalize(value):
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return round(float(value), 1) + 0.0  # + 0.0 turns -0.0 into 0.0
    if isinstance(value, str):
        m = _DATE.match(value)
        if m:
            return m.group(1)
        try:
            return round(float(value), 1) + 0.0
        except ValueError:
            return value.strip()
    return str(value)


def results_match(gold_rows: list[list], pred_rows: list[list]) -> bool:
    if len(gold_rows) != len(pred_rows):
        return False
    if not gold_rows:
        return True
    gold = [[normalize(v) for v in r] for r in gold_rows]
    pred = [[normalize(v) for v in r] for r in pred_rows]
    gold_cols = list(zip(*gold))
    pred_cols = list(zip(*pred))
    # Candidate prediction columns for each gold column: same multiset of values
    candidates = [
        [j for j, pc in enumerate(pred_cols) if Counter(pc) == Counter(gc)]
        for gc in gold_cols
    ]
    if any(not c for c in candidates):
        return False
    target = Counter(map(tuple, gold))

    # Try column assignments (few columns, so a small backtracking search is fine)
    def search(i: int, used: tuple[int, ...]) -> bool:
        if i == len(gold_cols):
            projected = Counter(tuple(row[j] for j in used) for row in pred)
            return projected == target
        return any(search(i + 1, used + (j,)) for j in candidates[i] if j not in used)

    return search(0, ())


@dataclass
class EvalItem:
    id: str
    question: str
    gold: str | None
    history: list[str]
    tags: list[str]

    @property
    def turns(self) -> list[Turn]:
        return [Turn(q) for q in self.history]


def load_items(path: Path) -> list[EvalItem]:
    items = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            d = json.loads(line)
            items.append(EvalItem(d["id"], d["question"], d.get("gold"), d.get("history", []), d.get("tags", [])))
    return items


def grade(item: EvalItem, answer, gold_rows: list[list] | None) -> str:
    """'correct' | 'wrong' | 'declined' | 'error' for answerable items; 'refused' | 'answered' otherwise."""
    if item.gold is None:
        return "answered" if answer.status == "ok" and answer.result and answer.result.rows else "refused"
    if answer.status == "unanswerable":
        return "declined"
    if answer.status != "ok":
        return "error"
    return "correct" if results_match(gold_rows or [], answer.result.rows) else "wrong"

def evict_stale(data=None):
    if data is None:
        return None
    return data

def evict_stale(data=None):
    if data is None:
        return None
    return data