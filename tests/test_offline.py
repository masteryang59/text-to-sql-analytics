from datetime import date

import pytest

from sqlchat.catalog import Catalog
from sqlchat.llm import Request, Turn
from sqlchat.offline import OfflineGenerator

from .conftest import TODAY

DIMS = {
    "category": ["Accessories", "Audio", "Cameras", "Laptops", "Monitors", "Smart Home"],
    "region": ["Asia Pacific", "Europe", "Latin America", "North America"],
    "country": ["Germany", "Japan", "United Kingdom", "United States"],
    "segment": ["Consumer", "Enterprise", "Small Business"],
    "channel": ["Online", "Partner", "Retail"],
    "product": ["Aero 14", "Aero 14 Pro", "Glow Bulb"],
    "rep": ["Ava Chen"],
}


@pytest.fixture(scope="module")
def gen():
    return OfflineGenerator(Catalog({}, date(2024, 1, 1), TODAY, DIMS))


def parse(gen, q):
    return gen.parse(q, TODAY)


def ask(gen, q, history=()):
    return gen.generate(Request(q, "", TODAY, date(2024, 1, 1), TODAY, history=[Turn(h) for h in history]))


@pytest.mark.parametrize("q,start,end", [
    ("revenue in 2025", "2025-01-01", "2026-01-01"),
    ("revenue in Q3 2025", "2025-07-01", "2025-10-01"),
    ("revenue in the third quarter of 2025", "2025-07-01", "2025-10-01"),
    ("revenue in march 2026", "2026-03-01", "2026-04-01"),
    ("revenue in march", "2026-03-01", "2026-04-01"),
    ("revenue in december", "2025-12-01", "2026-01-01"),  # the most recent December
    ("revenue last month", "2026-08-01", "2026-09-01"),
    ("revenue this month", "2026-09-01", "2026-10-01"),
    ("revenue last quarter", "2026-04-01", "2026-07-01"),
    ("revenue this year", "2026-01-01", "2026-10-01"),
    ("revenue last year", "2025-01-01", "2026-01-01"),
    ("revenue year to date", "2026-01-01", "2026-10-01"),
    ("revenue in the last 90 days", "2026-07-03", "2026-10-01"),
    ("revenue over the past 6 months", "2026-04-01", "2026-10-01"),
    ("revenue in the last two weeks", "2026-09-17", "2026-10-01"),
    ("revenue since march 2025", "2025-03-01", "2026-10-01"),
    ("revenue between 2024 and 2025", "2024-01-01", "2026-01-01"),
    ("revenue from q1 2025 to q2 2025", "2025-01-01", "2025-07-01"),
    ("revenue in the first half of 2026", "2026-01-01", "2026-07-01"),
    ("revenue yesterday", "2026-09-29", "2026-09-30"),
])
def test_periods(gen, q, start, end):
    p = parse(gen, q).period
    assert (p.start.isoformat(), p.end.isoformat()) == (start, end)


def test_may_as_a_word_is_not_a_month(gen):
    assert parse(gen, "may I see revenue by region").period is None


def test_two_years_compare_by_year(gen):
    intent = parse(gen, "revenue 2024 vs 2025")
    assert intent.years_compared
    assert "EXTRACT(YEAR FROM o.order_date)::int AS year" in ask(gen, "revenue 2024 vs 2025").sql


@pytest.mark.parametrize("q,metrics", [
    ("total revenue", ["revenue"]),
    ("sales by region", ["revenue"]),
    ("how many orders", ["orders"]),
    ("revenue and orders by channel", ["revenue", "orders"]),
    ("average order value by segment", ["aov"]),
    ("revenue from online orders", ["revenue"]),  # "orders" is weak
    ("gross margin by category", ["margin"]),
    ("profit by region", ["profit"]),
    ("refund rate by category", ["refund_rate"]),
    ("cancellation rate", ["cancel_rate"]),
    ("new customers per month", ["new_customers"]),
    ("how many customers placed an order in 2025", ["buyers"]),
    ("how many customers do we have", ["accounts"]),
    ("units sold by product", ["units"]),
])
def test_metrics(gen, q, metrics):
    assert parse(gen, q).metrics == metrics


def test_sales_rep_is_not_sales(gen):
    intent = parse(gen, "orders by sales rep")
    assert intent.metrics == ["orders"] and intent.dims == ["rep"]


def test_filters_match_longest_value_and_aliases(gen):
    intent = parse(gen, "units of the aero 14 pro in the US for enterprise customers")
    assert intent.filters == {"product": ["Aero 14 Pro"], "country": ["United States"], "segment": ["Enterprise"]}
    assert parse(gen, "laptop revenue in apac").filters == {"category": ["Laptops"], "region": ["Asia Pacific"]}


def test_several_values_of_one_dimension_are_compared(gen):
    intent = parse(gen, "compare online and retail revenue")
    assert intent.filters == {"channel": ["Online", "Retail"]} and intent.dims == ["channel"]


@pytest.mark.parametrize("q,limit,asc", [
    ("top 5 products by revenue", 5, False),
    ("bottom three categories by units", 3, True),
    ("which region had the most orders", 1, False),
    ("which regions had the most orders", 10, False),
    ("best-selling product", 1, False),
    ("revenue by category", None, False),
])
def test_ranking(gen, q, limit, asc):
    intent = parse(gen, q)
    assert (intent.limit, intent.ascending) == (limit, asc)


def test_which_month_ranks_months(gen):
    sql = ask(gen, "which month in 2025 had the highest revenue").sql
    assert "DATE_TRUNC('month', o.order_date)::date AS month" in sql
    assert sql.rstrip().endswith("LIMIT 1") and "ORDER BY revenue DESC" in sql


def test_best_selling_means_units_and_says_so(gen):
    draft = ask(gen, "best-selling products in 2025")
    assert "SUM(oi.quantity) AS units" in draft.sql
    assert "units sold" in draft.explanation


def test_sql_shape(gen):
    sql = ask(gen, "monthly revenue by category in Europe in 2025").sql
    assert sql.startswith("SELECT DATE_TRUNC('month', o.order_date)::date AS month,")
    for part in ("JOIN sales.categories c", "JOIN sales.regions r", "r.name = 'Europe'",
                 "o.status = 'completed'", "o.order_date >= DATE '2025-01-01'", "GROUP BY", "ORDER BY 1"):
        assert part in sql


def test_rates_count_all_orders(gen):
    sql = ask(gen, "refund rate by channel").sql
    assert "status = 'completed'" not in sql
    assert "FILTER (WHERE o.status = 'refunded')" in sql


def test_status_filter(gen):
    sql = ask(gen, "how many cancelled orders in 2025").sql
    assert "o.status = 'cancelled'" in sql


def test_customer_accounts_use_the_customers_table(gen):
    sql = ask(gen, "new customers by region in 2025").sql
    assert "FROM sales.customers cu" in sql and "cu.signup_date >= DATE '2025-01-01'" in sql
    assert ask(gen, "new customers by category").sql is None


def test_share_adds_a_window_column(gen):
    sql = ask(gen, "share of revenue by region").sql
    assert "OVER ()" in sql and "revenue_share_pct" in sql


def test_quotes_in_values_are_escaped(gen):
    g = OfflineGenerator(Catalog({}, None, TODAY, {"product": ["Kid's Tablet"]}))
    assert "p.name = 'Kid''s Tablet'" in g.generate(Request("revenue of kid's tablet", "", TODAY, None, None)).sql


@pytest.mark.parametrize("history,q,expect", [
    (["revenue by category in 2025"], "now only for Europe", ["r.name = 'Europe'", "c.name AS category", "2025-01-01"]),
    (["monthly revenue in 2026"], "what about units?", ["SUM(oi.quantity) AS units", "DATE_TRUNC('month'"]),
    (["top 5 products by revenue in 2025"], "and in 2024?", ["2024-01-01", "LIMIT 5"]),
    (["revenue by region last year"], "break it down by channel instead", ["o.channel AS channel"]),
    (["monthly revenue in 2025"], "by region instead", ["r.name AS region"]),
])
def test_follow_ups(gen, history, q, expect):
    sql = ask(gen, q, history).sql
    for part in expect:
        assert part in sql


def test_follow_up_instead_replaces_the_grouping(gen):
    sql = ask(gen, "by region instead", ["monthly revenue in 2025"]).sql
    assert "DATE_TRUNC" not in sql


def test_new_question_is_not_merged(gen):
    sql = ask(gen, "units by channel", ["revenue in Europe in 2025"]).sql
    assert "Europe" not in sql and "2025" not in sql


@pytest.mark.parametrize("q,phrase", [
    ("delete all cancelled orders", "can't change"),
    ("DROP TABLE orders", "can't change"),
    ("show customer emails", "personal data"),
    ("how much stock is in the warehouse", "stock"),
    ("forecast revenue next quarter", "future"),
    ("median order value", "medians"),
    ("customers who bought both laptops and cameras", "combine"),
    ("tell me a joke", "couldn't work out"),
])
def test_declines_instead_of_guessing(gen, q, phrase):
    draft = ask(gen, q)
    assert draft.sql is None
    assert phrase in draft.explanation


def test_explanation_states_assumptions(gen):
    text = ask(gen, "revenue by category last quarter").explanation
    assert "Revenue by category last quarter (1 Apr 2026 – 30 Jun 2026)." in text
    assert "Completed orders only." in text and "after discounts" in text
    assert "No measure was named" in ask(gen, "top 3 regions in 2025").explanation


def test_every_generated_query_runs(service):
    for q in ["monthly revenue by category in 2025", "top 5 customers by gross profit", "aov by segment and channel",
              "refund rate by region per year", "new customers per quarter by segment", "share of units by category",
              "discounts given by month in 2025", "average discount by channel", "margin for discontinued products"]:
        answer = service.ask(q)
        assert answer.status == "ok", (q, answer.error, answer.sql)
        assert answer.result.rows, q

def span_context(data=None):
    if data is None:
        return None
    return data

def span_context(data=None):
    if data is None:
        return None
    return data