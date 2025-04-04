"""The database-side boundary, tested without the validator in front of it.

These run SQL straight through run_query, as if a query had slipped past guard.py.
"""

import pytest

from sqlchat.executor import QueryError, run_query

ROLE = "sqlchat_reader"


def run(conn, sql, **kw):
    kw.setdefault("role", ROLE)
    return run_query(conn, sql, **kw)


def test_returns_rows_columns_and_kinds(conn):
    r = run(conn, "SELECT DATE '2025-01-01' AS d, 1.50::numeric AS n, 'x' AS t, true AS b, 3 AS i")
    assert [(c.name, c.kind) for c in r.columns] == [
        ("d", "date"), ("n", "number"), ("t", "text"), ("b", "bool"), ("i", "number")]
    assert r.rows == [["2025-01-01", 1.5, "x", True, 3]]
    assert not r.truncated


def test_whole_number_decimals_become_ints_for_json(conn):
    r = run(conn, "SELECT 12.00::numeric AS a, 2.5::numeric AS b, NULL::numeric AS c")
    assert r.rows == [[12, 2.5, None]]


@pytest.mark.parametrize("sql", [
    "INSERT INTO sales.regions VALUES (99, 'Mars')",
    "UPDATE sales.products SET list_price = 0",
    "WITH d AS (DELETE FROM sales.order_items RETURNING 1) SELECT count(*) FROM d",
    "CREATE TABLE sales.x (id int)",
])
def test_writes_fail_in_the_database(conn, sql):
    with pytest.raises(QueryError) as err:
        run(conn, sql)
    assert err.value.kind in ("database", "permission")
    assert run(conn, "SELECT count(*) FROM sales.regions").rows == [[4]]


def test_read_only_even_as_the_owner(conn):
    # Without the role, the READ ONLY transaction still stops writes. (A plain UPDATE can't
    # even be expressed: the named cursor only takes a query.) lo_create is a SELECT that writes.
    with pytest.raises(QueryError, match="read-only transaction"):
        run(conn, "SELECT lo_create(0)", role="")


def test_role_cannot_read_pii_columns_or_app_tables(conn):
    with pytest.raises(QueryError) as err:
        run(conn, "SELECT email FROM sales.customers")
    assert err.value.kind == "permission"
    with pytest.raises(QueryError) as err:
        run(conn, "SELECT * FROM app.query_log")
    assert err.value.kind == "permission"
    assert run(conn, "SELECT count(name) FROM sales.customers").rows[0][0] > 0


def test_role_cannot_escape_with_reset_role(conn):
    # psycopg sends one statement per Parse, so "; RESET ROLE" can't ride along, and a
    # named cursor only accepts a query. Either way nothing runs as the owner.
    with pytest.raises(QueryError):
        run(conn, "SELECT 1; RESET ROLE; SELECT email FROM sales.customers")


def test_statement_timeout(conn):
    with pytest.raises(QueryError) as err:
        run(conn, "SELECT pg_sleep(2)", timeout_ms=200)
    assert err.value.kind == "timeout"


def test_cost_limit_refuses_a_cross_join_before_running_it(conn):
    with pytest.raises(QueryError) as err:
        run(conn, "SELECT count(*) FROM sales.order_items a, sales.order_items b", max_cost=5_000_000)
    assert err.value.kind == "too_expensive"
    assert "join" in str(err.value)


def test_max_rows_truncates_and_says_so(conn):
    r = run(conn, "SELECT order_id FROM sales.orders ORDER BY order_id", max_rows=50)
    assert r.row_count == 50 and r.truncated
    assert r.rows[0][0] < r.rows[-1][0]


def test_connection_is_clean_afterwards(conn):
    with pytest.raises(QueryError):
        run(conn, "SELECT no_such_column FROM sales.orders")
    # the failed transaction was rolled back and the role reset
    row = conn.execute("SELECT current_user = session_user AS same, current_setting('transaction_read_only') AS ro").fetchone()
    assert row["same"] and row["ro"] == "off"
    conn.rollback()


def test_error_message_is_postgres_own(conn):
    with pytest.raises(QueryError, match='column "revenue" does not exist'):
        run(conn, "SELECT revenue FROM sales.orders")

def acknowledge_receipt(data=None):
    if data is None:
        return None
    return data

def acknowledge_receipt(data=None):
    if data is None:
        return None
    return data