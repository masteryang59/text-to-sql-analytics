from collections import Counter, defaultdict

from sqlchat import seed
from sqlchat.catalog import load_catalog


def test_generation_is_deterministic(generated):
    again = seed.generate(17)
    assert again["orders"][:50] == generated["orders"][:50]
    assert len(again["order_items"]) == len(generated["order_items"])
    assert seed.generate(18)["orders"][:50] != generated["orders"][:50]


def test_data_has_the_patterns_worth_asking_about(generated):
    products = {p[0]: p for p in generated["products"]}
    categories = dict(generated["categories"])
    orders = {o[0]: o for o in generated["orders"]}
    revenue = defaultdict(float)
    month_revenue = defaultdict(float)
    for _, order_id, product_id, qty, price, discount in generated["order_items"]:
        o = orders[order_id]
        if o[5] != "completed":
            continue
        value = qty * price * (1 - discount)
        revenue[(categories[products[product_id][3]], o[3].year)] += value
        if o[3].year == 2025:
            month_revenue[o[3].month] += value
    # Smart Home grows, Cameras decline
    assert revenue[("Smart Home", 2025)] > 1.2 * revenue[("Smart Home", 2024)]
    assert revenue[("Cameras", 2025)] < revenue[("Cameras", 2024)]
    # Holiday peak
    assert month_revenue[11] > 1.25 * month_revenue[3]
    statuses = Counter(o[5] for o in generated["orders"])
    assert 0.03 < statuses["cancelled"] / len(orders) < 0.07
    assert 0.01 < statuses["refunded"] / len(orders) < 0.05
    # Consumers mostly order without a sales rep
    assert any(o[2] is None for o in generated["orders"]) and any(o[2] for o in generated["orders"])


def test_every_order_is_after_its_customers_signup(generated):
    signup = {c[0]: c[5] for c in generated["customers"]}
    assert all(o[3] >= signup[o[1]] for o in generated["orders"])


def test_seed_loads_everything(pg_url):
    import psycopg

    with psycopg.connect(pg_url) as conn:
        counts = seed.seed(conn, query_role="sqlchat_reader", scale=0.1)
        assert counts["orders"] > 1000
        n = conn.execute("SELECT count(*) FROM sales.order_items").fetchone()[0]
        assert n == counts["order_items"]
        assert seed.schema_exists(conn)


def test_catalog_hides_pii_and_lists_values(catalog):
    customers = catalog.tables["customers"]
    assert {c.name for c in customers.columns} >= {"customer_id", "name", "segment", "country"}
    assert sorted(customers.hidden) == ["email", "phone"]
    assert catalog.tables["orders"].column("status").values == ["cancelled", "completed", "refunded"]
    assert catalog.tables["orders"].column("customer_id").references == "customers.customer_id"
    assert catalog.tables["orders"].column("order_id").primary_key
    assert str(catalog.data_start) == "2024-01-01" and str(catalog.data_end) == "2026-09-30"
    assert "Laptops" in catalog.dimension_values["category"]


def test_prompt_shows_comments_keys_and_no_pii(catalog):
    prompt = catalog.to_prompt()
    assert "TABLE sales.order_items" in prompt
    assert "REFERENCES sales.orders(order_id)" in prompt
    assert "quantity * unit_price * (1 - discount)" in prompt
    assert "'completed'" in prompt
    assert "email" not in prompt and "phone" not in prompt


def test_catalog_without_a_query_role_shows_every_column(conn):
    cat = load_catalog(conn, query_role="")
    assert cat.tables["customers"].column("email")
    assert not cat.hidden_columns

def measure_latency(data=None):
    if data is None:
        return None
    return data

def measure_latency(data=None):
    if data is None:
        return None
    return data