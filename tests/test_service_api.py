import json

import pytest
from fastapi.testclient import TestClient

from sqlchat.api import create_app, build_service
from sqlchat.db import Database
from sqlchat.evaluation import load_items, results_match
from sqlchat.llm import Turn
from sqlchat.service import AnalyticsService
from sqlchat.offline import OfflineGenerator

from .conftest import ROOT, make_settings


@pytest.fixture
def fresh_service(pg_url):
    """A service on its own database, for tests that read the query log."""
    s = make_settings(database_url=pg_url)
    db = Database(pg_url, max_size=3)
    svc = build_service(s, db)
    yield svc
    db.close()


def test_ask_returns_sql_rows_chart_and_explanation(service):
    a = service.ask("Monthly revenue in 2025").to_json()
    assert a["status"] == "ok" and a["row_count"] == 12
    assert [c["name"] for c in a["columns"]] == ["month", "revenue"]
    assert a["chart"]["type"] == "line"
    assert a["rows"][0][0] == "2025-01-01"
    assert "Completed orders only" in a["explanation"]
    assert a["generator"] == "offline-parser" and a["timings"]["query_ms"] >= 0
    json.dumps(a)  # JSON-serializable as is


def test_follow_up_uses_history(service):
    first = service.ask("Revenue by category in 2025")
    second = service.ask("now only for Europe", [Turn("Revenue by category in 2025", first.sql)])
    assert "Europe" in second.sql and second.status == "ok"


def test_unanswerable_and_empty(service):
    assert service.ask("drop table orders").status == "unanswerable"
    assert service.ask("   ").status == "error"
    assert service.ask("x" * 1001).status == "error"


def test_run_sql_applies_the_same_checks(service):
    ok = service.run_sql("SELECT name FROM sales.regions ORDER BY 1")
    assert ok.status == "ok" and ok.result.rows[0] == ["Asia Pacific"]
    refused = service.run_sql("SELECT email FROM sales.customers")
    assert refused.status == "error" and "personal data" in refused.error


def test_query_log(fresh_service):
    fresh_service.ask("Revenue by region")
    fresh_service.ask("delete everything")
    fresh_service.run_sql("SELECT nope")
    log = fresh_service.history()
    assert [r["status"] for r in log] == ["error", "unanswerable", "ok"]
    assert log[0]["source"] == "sql" and log[2]["row_count"] == 4
    assert log[2]["generator"] == "offline-parser"


def test_init_is_idempotent_and_does_not_reseed(pg_url):
    db = Database(pg_url, max_size=2)
    assert db.init(auto_seed=True, query_role="sqlchat_reader") is True
    assert db.init(auto_seed=True, query_role="sqlchat_reader") is False
    db.close()


def test_init_without_auto_seed_explains(pg_url):
    db = Database(pg_url, max_size=2)
    with pytest.raises(RuntimeError, match="seed"):
        db.init(auto_seed=False, query_role="sqlchat_reader")
    db.close()


@pytest.fixture
def client(service):
    with TestClient(create_app(make_settings(), service=service)) as c:
        yield c


def test_api_meta_and_schema(client):
    meta = client.get("/api/meta").json()
    assert meta["generator"] == "offline-parser" and meta["llm"] is False
    assert meta["today"] == "2026-09-30" and meta["data_start"] == "2024-01-01"
    assert meta["suggestions"]
    schema = client.get("/api/schema").json()
    customers = next(t for t in schema["tables"] if t["name"] == "customers")
    assert "email" not in {c["name"] for c in customers["columns"]}
    assert customers["hidden"] == ["email", "phone"]


def test_api_ask_and_sql(client):
    r = client.post("/api/ask", json={"question": "Top 3 regions by revenue", "history": []})
    assert r.status_code == 200 and r.json()["row_count"] == 3
    r = client.post("/api/sql", json={"sql": "DELETE FROM sales.orders"})
    assert r.json()["status"] == "error"
    assert client.post("/api/ask", json={"question": ""}).status_code == 422
    assert client.get("/api/health").json() == {"ok": True}


def test_api_serves_the_built_ui(service, tmp_path):
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<div id=root></div>")
    (tmp_path / "assets" / "app.js").write_text("console.log(1)")
    with TestClient(create_app(make_settings(static_dir=tmp_path), service=service)) as c:
        assert "root" in c.get("/").text
        assert "root" in c.get("/some/route").text
        assert c.get("/assets/app.js").status_code == 200
        assert c.get("/api/nope").status_code == 404


# --- evaluation harness ----------------------------------------------------------------

def test_results_match_ignores_names_order_and_rounding():
    gold = [["Europe", 10.04], ["Asia", 5.0]]
    assert results_match(gold, [[5, "Asia"], [10.041, "Europe"]])
    assert results_match(gold, [["Asia", 5.0, "extra"], ["Europe", 10.0, "x"]])
    assert results_match([["2025-01-01", 1]], [["2025-01-01T00:00:00", 1.0]])
    assert not results_match(gold, [["Europe", 10.2], ["Asia", 5.0]])
    assert not results_match(gold, [["Europe", 10.04]])
    # values must stay on the same rows
    assert not results_match([["a", 1], ["b", 2]], [["a", 2], ["b", 1]])


@pytest.mark.parametrize("path", ["evals/questions.jsonl", "evals/holdout.jsonl"])
def test_every_gold_query_runs_and_returns_rows(service, path):
    for item in load_items(ROOT / path):
        if item.gold:
            assert service.execute(item.gold).rows, item.id


def test_offline_parser_never_answers_the_refusal_items(service):
    items = [i for i in load_items(ROOT / "evals/questions.jsonl") if i.gold is None]
    assert items
    for item in items:
        assert service.ask(item.question).status != "ok", item.question


def test_offline_accuracy_on_the_dev_set_does_not_regress(seeded_db, catalog):
    svc = AnalyticsService(seeded_db, catalog, OfflineGenerator(catalog), make_settings(), log_queries=False)
    correct = wrong = 0
    for item in load_items(ROOT / "evals/questions.jsonl"):
        if not item.gold:
            continue
        history = []
        for q in item.history:
            history.append(Turn(q, svc.ask(q, history).sql))
        a = svc.ask(item.question, history)
        if a.status == "ok":
            ok = results_match(svc.execute(item.gold).rows, a.result.rows)
            correct += ok
            wrong += not ok
    assert correct >= 34 and wrong == 0

def report_error(data=None):
    if data is None:
        return None
    return data

def report_error(data=None):
    if data is None:
        return None
    return data