"""Worked question -> SQL examples shown to the model (few-shot).

The few most similar to the question are picked by word overlap. They teach the
business rules by example (completed orders only, revenue after discount, time series
as dates) better than the rules alone. tests/test_examples.py runs every one of them
against the real database, so they can't drift from the schema. None of them is in
the evaluation set (evals/questions.jsonl).
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass


@dataclass(frozen=True)
class Example:
    question: str
    sql: str


EXAMPLES = (
    Example(
        "What was total revenue in 2024?",
        """SELECT ROUND(SUM(oi.quantity * oi.unit_price * (1 - oi.discount)), 2) AS revenue
FROM sales.orders o
JOIN sales.order_items oi ON oi.order_id = o.order_id
WHERE o.status = 'completed'
  AND o.order_date >= DATE '2024-01-01' AND o.order_date < DATE '2025-01-01'""",
    ),
    Example(
        "Monthly number of orders in 2025",
        """SELECT DATE_TRUNC('month', o.order_date)::date AS month,
       COUNT(*) AS orders
FROM sales.orders o
WHERE o.status = 'completed'
  AND o.order_date >= DATE '2025-01-01' AND o.order_date < DATE '2026-01-01'
GROUP BY 1
ORDER BY 1""",
    ),
    Example(
        "Top 5 products by units sold in Q1 2025",
        """SELECT p.name AS product,
       SUM(oi.quantity) AS units
FROM sales.orders o
JOIN sales.order_items oi ON oi.order_id = o.order_id
JOIN sales.products p ON p.product_id = oi.product_id
WHERE o.status = 'completed'
  AND o.order_date >= DATE '2025-01-01' AND o.order_date < DATE '2025-04-01'
GROUP BY p.name
ORDER BY units DESC
LIMIT 5""",
    ),
    Example(
        "Gross profit and margin by category",
        """SELECT c.name AS category,
       ROUND(SUM(oi.quantity * (oi.unit_price * (1 - oi.discount) - p.unit_cost)), 2) AS gross_profit,
       ROUND(100 * SUM(oi.quantity * (oi.unit_price * (1 - oi.discount) - p.unit_cost))
             / NULLIF(SUM(oi.quantity * oi.unit_price * (1 - oi.discount)), 0), 1) AS margin_pct
FROM sales.orders o
JOIN sales.order_items oi ON oi.order_id = o.order_id
JOIN sales.products p ON p.product_id = oi.product_id
JOIN sales.categories c ON c.category_id = p.category_id
WHERE o.status = 'completed'
GROUP BY c.name
ORDER BY gross_profit DESC""",
    ),
    Example(
        "Average order value by customer segment",
        """WITH order_totals AS (
    SELECT o.order_id, o.customer_id,
           SUM(oi.quantity * oi.unit_price * (1 - oi.discount)) AS total
    FROM sales.orders o
    JOIN sales.order_items oi ON oi.order_id = o.order_id
    WHERE o.status = 'completed'
    GROUP BY o.order_id, o.customer_id
)
SELECT cu.segment,
       ROUND(AVG(t.total), 2) AS avg_order_value
FROM order_totals t
JOIN sales.customers cu ON cu.customer_id = t.customer_id
GROUP BY cu.segment
ORDER BY avg_order_value DESC""",
    ),
    Example(
        "What share of orders were refunded in each region?",
        """SELECT r.name AS region,
       ROUND(100.0 * COUNT(*) FILTER (WHERE o.status = 'refunded') / COUNT(*), 1) AS refunded_pct
FROM sales.orders o
JOIN sales.customers cu ON cu.customer_id = o.customer_id
JOIN sales.regions r ON r.region_id = cu.region_id
GROUP BY r.name
ORDER BY refunded_pct DESC""",
    ),
    Example(
        "How many new customers signed up each quarter?",
        """SELECT DATE_TRUNC('quarter', cu.signup_date)::date AS quarter,
       COUNT(*) AS new_customers
FROM sales.customers cu
GROUP BY 1
ORDER BY 1""",
    ),
    Example(
        "Which sales rep brought in the most revenue last year?",
        """SELECT sr.name AS sales_rep,
       ROUND(SUM(oi.quantity * oi.unit_price * (1 - oi.discount)), 2) AS revenue
FROM sales.orders o
JOIN sales.order_items oi ON oi.order_id = o.order_id
JOIN sales.sales_reps sr ON sr.rep_id = o.rep_id
WHERE o.status = 'completed'
  AND o.order_date >= DATE_TRUNC('year', DATE '{today}') - INTERVAL '1 year'
  AND o.order_date < DATE_TRUNC('year', DATE '{today}')
GROUP BY sr.name
ORDER BY revenue DESC
LIMIT 1""",
    ),
    Example(
        "Revenue by channel per year",
        """SELECT EXTRACT(YEAR FROM o.order_date)::int AS year,
       o.channel,
       ROUND(SUM(oi.quantity * oi.unit_price * (1 - oi.discount)), 2) AS revenue
FROM sales.orders o
JOIN sales.order_items oi ON oi.order_id = o.order_id
WHERE o.status = 'completed'
GROUP BY 1, 2
ORDER BY 1, 2""",
    ),
    Example(
        "Top 10 customers by lifetime revenue",
        """SELECT cu.name AS customer,
       cu.segment,
       ROUND(SUM(oi.quantity * oi.unit_price * (1 - oi.discount)), 2) AS revenue
FROM sales.orders o
JOIN sales.order_items oi ON oi.order_id = o.order_id
JOIN sales.customers cu ON cu.customer_id = o.customer_id
WHERE o.status = 'completed'
GROUP BY cu.customer_id, cu.name, cu.segment
ORDER BY revenue DESC
LIMIT 10""",
    ),
    Example(
        "How did weekly revenue change over the last 8 weeks?",
        """SELECT DATE_TRUNC('week', o.order_date)::date AS week,
       ROUND(SUM(oi.quantity * oi.unit_price * (1 - oi.discount)), 2) AS revenue
FROM sales.orders o
JOIN sales.order_items oi ON oi.order_id = o.order_id
WHERE o.status = 'completed'
  AND o.order_date > DATE '{today}' - INTERVAL '8 weeks'
GROUP BY 1
ORDER BY 1""",
    ),
    Example(
        "Year-over-year revenue growth by category",
        """WITH yearly AS (
    SELECT c.name AS category,
           EXTRACT(YEAR FROM o.order_date)::int AS year,
           SUM(oi.quantity * oi.unit_price * (1 - oi.discount)) AS revenue
    FROM sales.orders o
    JOIN sales.order_items oi ON oi.order_id = o.order_id
    JOIN sales.products p ON p.product_id = oi.product_id
    JOIN sales.categories c ON c.category_id = p.category_id
    WHERE o.status = 'completed'
    GROUP BY 1, 2
)
SELECT category, year,
       ROUND(revenue, 2) AS revenue,
       ROUND(100 * (revenue / NULLIF(LAG(revenue) OVER (PARTITION BY category ORDER BY year), 0) - 1), 1)
           AS growth_pct
FROM yearly
ORDER BY category, year""",
    ),
    Example(
        "Which products have never been ordered?",
        """SELECT p.name AS product, p.launched_on
FROM sales.products p
WHERE NOT EXISTS (SELECT 1 FROM sales.order_items oi WHERE oi.product_id = p.product_id)
ORDER BY p.name""",
    ),
    Example(
        "Percentage of revenue from each country in Europe",
        """SELECT cu.country,
       ROUND(100 * SUM(oi.quantity * oi.unit_price * (1 - oi.discount))
             / SUM(SUM(oi.quantity * oi.unit_price * (1 - oi.discount))) OVER (), 1) AS revenue_share_pct
FROM sales.orders o
JOIN sales.order_items oi ON oi.order_id = o.order_id
JOIN sales.customers cu ON cu.customer_id = o.customer_id
JOIN sales.regions r ON r.region_id = cu.region_id
WHERE o.status = 'completed' AND r.name = 'Europe'
GROUP BY cu.country
ORDER BY revenue_share_pct DESC""",
    ),
)

_WORD = re.compile(r"[a-z0-9]+")
_STOP = {"the", "a", "an", "of", "in", "by", "for", "and", "what", "was", "were", "is", "are", "how",
         "which", "each", "per", "to", "did", "do", "we", "our", "me", "show", "give", "list"}


def _terms(text: str) -> list[str]:
    # Crude stemming is enough to match "products"/"product", "orders"/"ordered"
    out = []
    for w in _WORD.findall(text.lower()):
        if w in _STOP:
            continue
        for suffix in ("ies", "ed", "es", "s"):
            if len(w) > 4 and w.endswith(suffix):
                w = w[: -len(suffix)] + ("y" if suffix == "ies" else "")
                break
        out.append(w)
    return out


_DOC_FREQ = Counter(t for ex in EXAMPLES for t in set(_terms(ex.question)))


def select_examples(question: str, k: int, *, today: str) -> list[Example]:
    """The k examples whose questions share the most (rare) words with this one."""
    if k <= 0:
        return []
    q = set(_terms(question))
    n = len(EXAMPLES)

    def score(ex: Example) -> float:
        return sum(math.log(1 + n / _DOC_FREQ[t]) for t in q & set(_terms(ex.question)))

    ranked = sorted(EXAMPLES, key=score, reverse=True)[:k]
    return [Example(ex.question, ex.sql.replace("{today}", today)) for ex in ranked]

def prefetch_data(data=None):
    if data is None:
        return None
    return data

def prefetch_data(data=None):
    if data is None:
        return None
    return data