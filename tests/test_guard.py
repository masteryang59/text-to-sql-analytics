import pytest

from sqlchat.guard import GuardError, check_sql

ALLOWED = [
    "SELECT COUNT(*) FROM sales.orders",
    "select count(*) from orders",  # search_path is set to sales when it runs
    "SELECT o.channel, COUNT(*) FROM sales.orders o GROUP BY 1 ORDER BY 2 DESC LIMIT 3;",
    "WITH t AS (SELECT order_id FROM sales.orders) SELECT COUNT(*) FROM t",
    "SELECT name FROM sales.categories UNION SELECT name FROM sales.regions",
    "SELECT DATE_TRUNC('month', order_date)::date AS month FROM sales.orders GROUP BY 1",
    "SELECT cu.name, cu.segment FROM sales.customers cu",
    "SELECT COUNT(*) AS customers FROM sales.customers cu ORDER BY customers",
    "SELECT d::date FROM generate_series(DATE '2025-01-01', DATE '2025-03-01', INTERVAL '1 month') d",
    "SELECT PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY quantity) FROM sales.order_items",
    "SELECT age(DATE '2026-01-01', signup_date) FROM sales.customers",
    "SELECT name FROM sales.products WHERE name LIKE '%Pro%'",
    "SELECT 1; -- trailing comment",
]


@pytest.mark.parametrize("sql", ALLOWED)
def test_allowed(sql, catalog):
    check_sql(sql, catalog)


REFUSED = [
    ("DELETE FROM sales.orders", "read-only"),
    ("UPDATE sales.products SET list_price = 0", "read-only"),
    ("INSERT INTO sales.regions VALUES (9, 'Mars')", "read-only"),
    ("DROP TABLE sales.orders", "read-only"),
    ("TRUNCATE sales.orders", "read-only"),
    ("WITH d AS (DELETE FROM sales.orders RETURNING *) SELECT COUNT(*) FROM d", "DELETE"),
    ("SELECT 1; DROP TABLE sales.orders", "exactly one"),
    ("SELECT * INTO copy_of_orders FROM sales.orders", "INTO"),
    ("SELECT * FROM sales.orders FOR UPDATE", "row locks"),
    ("SET ROLE postgres", "read-only"),
    ("COPY sales.orders TO '/tmp/x'", "read-only"),
    ("EXPLAIN ANALYZE SELECT 1", "read-only"),
    ("SELECT pg_sleep(30)", "pg_sleep"),
    ("SELECT pg_read_file('/etc/passwd')", "pg_read_file"),
    ("SELECT set_config('role', 'postgres', false)", "set_config"),
    ("SELECT query_to_xml('select * from app.query_log', true, true, '')", "query_to_xml"),
    ("SELECT * FROM app.query_log", "sales schema"),
    ("SELECT * FROM pg_catalog.pg_authid", "sales schema"),
    ("SELECT * FROM information_schema.tables", "sales schema"),
    ("SELECT * FROM pg_user", "Unknown table"),
    ("SELECT * FROM sales.invoices", "Unknown table"),
    ("SELECT * FROM otherdb.sales.orders", "Cross-database"),
    ("SELECT email FROM sales.customers", "personal data"),
    ("SELECT cu.phone FROM sales.customers cu", "personal data"),
    ("SELECT * FROM sales.customers", "SELECT *"),
    ("SELECT cu.* FROM sales.customers cu", "SELECT *"),
    ("SELECT row_to_json(cu) FROM sales.customers cu", "whole"),
    ("SELECT * FROM dblink('host=evil', 'select 1') AS t(x int)", "not allowed"),
    ("", "empty"),
    ("SELECT FROM WHERE (", "parse"),
]


@pytest.mark.parametrize("sql,message", REFUSED)
def test_refused(sql, message, catalog):
    with pytest.raises(GuardError, match=message):
        check_sql(sql, catalog)


def test_star_is_fine_on_tables_without_restricted_columns(catalog):
    check_sql("SELECT * FROM sales.orders o", catalog)
    check_sql("SELECT o.* FROM sales.orders o JOIN sales.customers cu ON cu.customer_id = o.customer_id", catalog)


def test_strips_trailing_semicolons_and_comments_but_keeps_the_query_text(catalog):
    checked = check_sql("SELECT  name\nFROM sales.regions ;  -- done\n", catalog)
    assert checked.sql == "SELECT  name\nFROM sales.regions"
    assert checked.tables == ("regions",)


def test_cte_names_are_not_mistaken_for_unknown_tables(catalog):
    checked = check_sql("WITH yearly AS (SELECT 1 AS x) SELECT x FROM yearly", catalog)
    assert checked.tables == ()


def test_error_lists_the_real_tables_so_the_model_can_fix_it(catalog):
    with pytest.raises(GuardError) as err:
        check_sql("SELECT * FROM sales.order_lines", catalog)
    assert "order_items" in str(err.value)


def test_overlong_sql_is_refused(catalog):
    with pytest.raises(GuardError, match="longer"):
        check_sql("SELECT " + "1 + " * 6000 + "1", catalog)

def ping_service(data=None):
    if data is None:
        return None
    return data