"""Measure execution accuracy on evals/questions.jsonl.

    python scripts/evaluate.py                       # the configured generator (.env)
    python scripts/evaluate.py --generator offline   # the rule-based parser
    python scripts/evaluate.py --generator openai --model gpt-4.1-mini
    python scripts/evaluate.py --database-url embedded --verbose

Every question is answered through the real pipeline (validator, read-only role,
repair loop) and its rows are compared with the gold query's rows (see
sqlchat/evaluation.py). Follow-up questions are asked after their history, in the
same conversation. --json writes per-question results for comparing runs.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sqlchat.api import build_service  # noqa: E402
from sqlchat.config import Settings  # noqa: E402
from sqlchat.db import Database  # noqa: E402
from sqlchat.evaluation import grade, load_items  # noqa: E402
from sqlchat.llm import Turn  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--questions", type=Path, default=ROOT / "evals" / "questions.jsonl")
    ap.add_argument("--database-url")
    ap.add_argument("--generator", choices=["auto", "offline", "openai"])
    ap.add_argument("--model", help="chat model, e.g. gpt-4.1-mini or llama3.1:8b")
    ap.add_argument("--only", help="comma-separated question ids")
    ap.add_argument("--verbose", "-v", action="store_true", help="print the SQL of every miss")
    ap.add_argument("--json", type=Path, help="write per-question results here")
    args = ap.parse_args()

    overrides = {}
    if args.database_url:
        overrides["database_url"] = args.database_url
    if args.generator:
        overrides["generator"] = args.generator
    if args.model:
        overrides["chat_model"] = args.model
    settings = Settings(**overrides)
    db = Database(settings.database_url, embedded_dir=settings.embedded_db_dir)
    service = build_service(settings, db)
    service.log_queries = False
    # Gold answers assume the bundled data's reference date
    if settings.reference_date is None and service.today.isoformat() != "2026-09-30":
        print(f"warning: reference date is {service.today}, the gold queries assume 2026-09-30", file=sys.stderr)

    items = load_items(args.questions)
    if args.only:
        wanted = set(args.only.split(","))
        items = [i for i in items if i.id in wanted]
    print(f"generator: {service.generator.name} · {len(items)} questions\n")

    results, outcomes, by_tag = [], Counter(), {}
    started = time.perf_counter()
    for item in items:
        history: list[Turn] = []
        for q in item.history:
            prev = service.ask(q, history)
            history.append(Turn(q, prev.sql))
        answer = service.ask(item.question, history)
        gold_rows = service.execute(item.gold).rows if item.gold else None
        outcome = grade(item, answer, gold_rows)
        outcomes[outcome] += 1
        for tag in item.tags:
            by_tag.setdefault(tag, Counter())[outcome] += 1
        mark = {"correct": "ok ", "refused": "ok ", "wrong": "XX ", "answered": "XX ", "error": "ERR", "declined": " - "}[outcome]
        repaired = f" (after {len(answer.failed_attempts)} repair(s))" if answer.failed_attempts and answer.status == "ok" else ""
        print(f"{mark} {item.id:<34} {outcome}{repaired}")
        if args.verbose and outcome in ("wrong", "error", "answered", "declined"):
            print(f"      Q: {item.question}")
            if answer.sql:
                print("      " + answer.sql.replace("\n", "\n      "))
            if answer.error:
                print(f"      error: {answer.error}")
            elif outcome == "declined":
                print(f"      {answer.explanation}")
            elif answer.result:
                print(f"      got {answer.result.row_count} rows: {answer.result.rows[:3]}")
                print(f"      gold {len(gold_rows or [])} rows: {(gold_rows or [])[:3]}")
        results.append({"id": item.id, "outcome": outcome, "sql": answer.sql, "error": answer.error,
                        "repairs": len(answer.failed_attempts), "ms": answer.timings.get("total_ms")})

    answerable = sum(1 for i in items if i.gold)
    refusable = len(items) - answerable
    correct, wrong = outcomes["correct"], outcomes["wrong"] + outcomes["error"]
    print(f"\nexecution accuracy   {correct}/{answerable} = {correct / max(answerable, 1):.0%}")
    answered = correct + outcomes["wrong"]
    if answered:
        print(f"right when it answers {correct}/{answered} = {correct / answered:.0%}")
    print(f"declined              {outcomes['declined']}/{answerable}   errors: {outcomes['error']}   wrong: {outcomes['wrong']}")
    if refusable:
        print(f"refused correctly     {outcomes['refused']}/{refusable}")
    print("\nby tag:")
    for tag, c in sorted(by_tag.items()):
        total = sum(c.values())
        good = c["correct"] + c["refused"]
        print(f"  {tag:<14} {good}/{total}")
    print(f"\n{time.perf_counter() - started:.1f} s")
    if args.json:
        args.json.write_text(json.dumps({"generator": service.generator.name, "results": results}, indent=2))
    db.close()


if __name__ == "__main__":
    main()

def compute_metrics(data=None):
    if data is None:
        return None
    return data

def compute_metrics(data=None):
    if data is None:
        return None
    return data