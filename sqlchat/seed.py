"""The demo sales database: schema, comments, a read-only role and generated data.

The data is generated from a fixed seed, so every install has the same numbers and
the evaluation questions have stable answers. It has the patterns a real sales
database has, so questions return something worth charting: growth over time,
a November/December peak, a back-to-school bump for laptops, a category that
grows (Smart Home) and one that declines (Cameras), business customers who buy
in bulk through sales reps, discounts in Black Friday week, a 2026 price rise,
and cancelled and refunded orders that must be left out of revenue.
"""

from __future__ import annotations

import logging
import math
import random
from dataclasses import dataclass
from datetime import date, timedelta

import psycopg
from psycopg import sql
from psycopg.rows import tuple_row

log = logging.getLogger(__name__)

SCHEMA = "sales"
START = date(2024, 1, 1)
END = date(2026, 9, 30)
# Columns the query role can't read. They are left out of the schema shown to the model.
PII_COLUMNS = {"customers": ("email", "phone")}

DDL = """
CREATE SCHEMA sales;

CREATE TABLE sales.regions (
    region_id smallint PRIMARY KEY,
    name      text NOT NULL UNIQUE
);

CREATE TABLE sales.categories (
    category_id smallint PRIMARY KEY,
    name        text NOT NULL UNIQUE
);

CREATE TABLE sales.products (
    product_id   integer PRIMARY KEY,
    sku          text NOT NULL UNIQUE,
    name         text NOT NULL,
    category_id  smallint NOT NULL REFERENCES sales.categories,
    list_price   numeric(10,2) NOT NULL,
    unit_cost    numeric(10,2) NOT NULL,
    launched_on  date NOT NULL,
    discontinued boolean NOT NULL DEFAULT false
);

CREATE TABLE sales.sales_reps (
    rep_id    integer PRIMARY KEY,
    name      text NOT NULL,
    region_id smallint NOT NULL REFERENCES sales.regions,
    hired_on  date NOT NULL
);

CREATE TABLE sales.customers (
    customer_id integer PRIMARY KEY,
    name        text NOT NULL,
    segment     text NOT NULL CHECK (segment IN ('Consumer', 'Small Business', 'Enterprise')),
    country     text NOT NULL,
    region_id   smallint NOT NULL REFERENCES sales.regions,
    signup_date date NOT NULL,
    email       text NOT NULL,
    phone       text NOT NULL
);

CREATE TABLE sales.orders (
    order_id      integer PRIMARY KEY,
    customer_id   integer NOT NULL REFERENCES sales.customers,
    rep_id        integer REFERENCES sales.sales_reps,
    order_date    date NOT NULL,
    channel       text NOT NULL CHECK (channel IN ('Online', 'Retail', 'Partner')),
    status        text NOT NULL CHECK (status IN ('completed', 'cancelled', 'refunded')),
    shipping_cost numeric(8,2) NOT NULL
);

CREATE TABLE sales.order_items (
    order_item_id integer PRIMARY KEY,
    order_id      integer NOT NULL REFERENCES sales.orders,
    product_id    integer NOT NULL REFERENCES sales.products,
    quantity      integer NOT NULL CHECK (quantity > 0),
    unit_price    numeric(10,2) NOT NULL,
    discount      numeric(4,3) NOT NULL DEFAULT 0 CHECK (discount >= 0 AND discount < 1)
);
"""

INDEXES = """
CREATE INDEX orders_date_idx ON sales.orders (order_date);
CREATE INDEX orders_customer_idx ON sales.orders (customer_id);
CREATE INDEX order_items_order_idx ON sales.order_items (order_id);
CREATE INDEX order_items_product_idx ON sales.order_items (product_id);
CREATE INDEX customers_region_idx ON sales.customers (region_id);
"""

# The model reads these (they're part of the schema in its prompt), so they say what
# each table means and how the business defines its numbers.
COMMENTS = {
    "regions": "Sales regions.",
    "categories": "Product categories.",
    "products": "Products in the catalog. list_price is today's price; what a customer paid is order_items.unit_price.",
    "products.list_price": "Current catalog price in USD.",
    "products.unit_cost": "What one unit costs us in USD. Gross profit = revenue - quantity * unit_cost.",
    "products.launched_on": "Date the product went on sale.",
    "products.discontinued": "True when the product is no longer sold.",
    "sales_reps": "Account managers. Each covers one region.",
    "customers": "One row per customer account, consumers and businesses.",
    "customers.country": "Billing country.",
    "customers.region_id": "Region of the billing country.",
    "customers.signup_date": "Date the account was created. New customers in a period = accounts with signup_date in it.",
    "orders": "One row per order. Only status = 'completed' counts towards revenue, units and order counts unless the question asks about cancelled or refunded orders.",
    "orders.rep_id": "The sales rep who handled the order. NULL for self-service orders (most consumer orders).",
    "orders.order_date": "Date the order was placed. Use it for every time filter and trend.",
    "orders.shipping_cost": "Shipping charged to the customer in USD. Not part of revenue.",
    "order_items": "Order lines. Revenue of a line = quantity * unit_price * (1 - discount).",
    "order_items.unit_price": "Price per unit before discount, in USD, as charged on the order date.",
    "order_items.discount": "Discount as a fraction, e.g. 0.15 = 15% off.",
}


@dataclass(frozen=True)
class CategorySpec:
    name: str
    price_range: tuple[int, int]
    # Relative share of order lines at the start of 2024, and how it changes per year
    weight: float
    yearly_growth: float
    products: tuple[str, ...]


CATEGORIES = (
    CategorySpec("Laptops", (749, 2299), 0.9, 0.06, (
        "Aero 13", "Aero 14 Pro", "Aero 16", "Strata 14", "Strata 15 Business", "Volt 15 Gaming",
        "Volt 17 Gaming", "Lumen 13 Air", "Lumen 15", "Forge 16 Workstation")),
    CategorySpec("Monitors", (169, 949), 1.0, 0.04, (
        "Nimbus 24", "Nimbus 27", "Nimbus 27 4K", "Nimbus 32 4K", "Vista 34 Ultrawide",
        "Vista 49 Ultrawide", "Pulse 27 240Hz", "Pulse 24 165Hz", "Studio 27 5K")),
    CategorySpec("Audio", (39, 399), 1.3, 0.02, (
        "Echo Buds", "Echo Buds Pro", "Echo Over-Ear", "Echo Over-Ear ANC", "Halo Soundbar",
        "Halo Soundbar Max", "Pebble Speaker", "Pebble Speaker XL", "Studio Mic USB", "Echo Sport")),
    CategorySpec("Smart Home", (25, 279), 0.7, 0.45, (
        "Glow Bulb", "Glow Bulb 4-Pack", "Glow Light Strip", "Sentry Doorbell", "Sentry Cam Indoor",
        "Sentry Cam Outdoor", "Hearth Thermostat", "Hearth Smoke Sensor", "Hub Mini", "Hub Max")),
    CategorySpec("Accessories", (9, 129), 2.2, 0.03, (
        "Flex USB-C Cable", "Flex USB-C Hub", "Dock Pro", "Charge 65W", "Charge 100W", "Glide Mouse",
        "Glide Mouse Pro", "Type Keyboard", "Type Keyboard Mechanical", "Sleeve 14", "Sleeve 16",
        "Stand Aluminium")),
    CategorySpec("Cameras", (279, 1599), 0.6, -0.22, (
        "Optic M50", "Optic M70", "Optic Z9 Mirrorless", "Optic Z7 Mirrorless", "Action Cam 4",
        "Action Cam 5", "Lens 35mm", "Lens 85mm")),
)

REGIONS = {
    "North America": (("United States", 0.86), ("Canada", 0.14)),
    "Europe": (("United Kingdom", 0.24), ("Germany", 0.26), ("France", 0.18), ("Netherlands", 0.1),
               ("Spain", 0.12), ("Sweden", 0.1)),
    "Asia Pacific": (("Australia", 0.32), ("Japan", 0.34), ("Singapore", 0.12), ("India", 0.22)),
    "Latin America": (("Brazil", 0.45), ("Mexico", 0.35), ("Chile", 0.1), ("Colombia", 0.1)),
}
REGION_WEIGHTS = {"North America": 0.42, "Europe": 0.31, "Asia Pacific": 0.18, "Latin America": 0.09}
# Latin America grows fastest, so "which region grew most" has a clear answer.
REGION_GROWTH = {"North America": 0.10, "Europe": 0.12, "Asia Pacific": 0.18, "Latin America": 0.40}

SEGMENTS = (("Consumer", 0.68), ("Small Business", 0.25), ("Enterprise", 0.07))
CHANNELS = {
    "Consumer": (("Online", 0.72), ("Retail", 0.26), ("Partner", 0.02)),
    "Small Business": (("Online", 0.52), ("Retail", 0.18), ("Partner", 0.30)),
    "Enterprise": (("Online", 0.15), ("Retail", 0.05), ("Partner", 0.80)),
}
# Order volume by month (Jan..Dec), relative to the average month
SEASONALITY = (0.86, 0.80, 0.92, 0.93, 0.96, 0.94, 0.92, 1.02, 1.04, 1.0, 1.30, 1.45)

FIRST = ("Ava", "Liam", "Mia", "Noah", "Zoe", "Ethan", "Lena", "Omar", "Sofia", "Kai", "Hana", "Lucas",
         "Ines", "Mateo", "Yuki", "Aria", "Felix", "Nora", "Ravi", "Elena", "Theo", "Maya", "Jonas",
         "Priya", "Diego", "Clara", "Sam", "Leila", "Marco", "Amara")
LAST = ("Chen", "Okafor", "Silva", "Novak", "Kim", "Garcia", "Muller", "Rossi", "Tanaka", "Haddad",
        "Larsen", "Patel", "Dubois", "Kowalski", "Santos", "Nguyen", "Fischer", "Ali", "Moreau",
        "Jensen", "Costa", "Ivanova", "Brooks", "Sato", "Reyes", "Lindqvist", "Mensah", "Varga")
BIZ_A = ("Blue", "North", "Bright", "Iron", "Cedar", "Summit", "Harbor", "Pixel", "Atlas", "Nova",
         "Orbit", "Granite", "Maple", "Signal", "Vertex", "Willow", "Copper", "Lumen", "Delta", "Echo")
BIZ_B = ("Labs", "Studio", "Logistics", "Partners", "Systems", "Works", "Analytics", "Health",
         "Foods", "Design", "Capital", "Media", "Robotics", "Energy", "Legal", "Retail")
BIZ_C = ("Ltd", "GmbH", "Inc", "LLC", "SA", "BV", "Pty Ltd", "KK", "AB", "SAS")


def _pick(rng: random.Random, pairs):
    names, weights = zip(*pairs)
    return rng.choices(names, weights=weights)[0]


def generate(seed: int = 17, *, scale: float = 1.0) -> dict[str, list[tuple]]:
    """Every table's rows as tuples, in column order. `scale` multiplies order volume."""
    rng = random.Random(seed)
    tables: dict[str, list[tuple]] = {}

    region_ids = {name: i + 1 for i, name in enumerate(REGIONS)}
    tables["regions"] = [(i, name) for name, i in region_ids.items()]
    tables["categories"] = [(i + 1, c.name) for i, c in enumerate(CATEGORIES)]

    products = []
    by_category: dict[int, list[tuple]] = {}
    pid = 100
    for ci, cat in enumerate(CATEGORIES, start=1):
        lo, hi = cat.price_range
        for k, pname in enumerate(cat.products):
            pid += 1
            # Spread prices across the range, so each category has cheap and premium models
            frac = (k + rng.random()) / len(cat.products)
            price = round(math.exp(math.log(lo) + frac * (math.log(hi) - math.log(lo)))) - 0.01
            cost = round(price * rng.uniform(0.52, 0.74), 2)
            launched = START - timedelta(days=rng.randint(60, 900))
            if rng.random() < 0.22:  # launched during the data range
                launched = START + timedelta(days=rng.randint(90, 780))
            discontinued = rng.random() < 0.12 and launched < START
            row = (pid, f"{cat.name[:3].upper()}-{pid}", pname, ci, price, cost, launched, discontinued)
            products.append(row)
            by_category.setdefault(ci, []).append(row)
    tables["products"] = products
    # A discontinued product stopped selling at some point in the range
    stop_selling = {p[0]: START + timedelta(days=rng.randint(120, 700)) for p in products if p[7]}

    reps = []
    reps_by_region: dict[int, list[int]] = {}
    rep_id = 0
    for region, rid in region_ids.items():
        for _ in range(4 if region in ("North America", "Europe") else 2):
            rep_id += 1
            name = f"{rng.choice(FIRST)} {rng.choice(LAST)}"
            reps.append((rep_id, name, rid, START - timedelta(days=rng.randint(100, 1500))))
            reps_by_region.setdefault(rid, []).append(rep_id)
    tables["sales_reps"] = reps

    customers = []
    n_customers = max(200, int(2600 * scale))
    span = (END - date(2023, 6, 1)).days
    for cid in range(1, n_customers + 1):
        segment = _pick(rng, SEGMENTS)
        region = _pick(rng, REGION_WEIGHTS.items())
        country = _pick(rng, REGIONS[region])
        # More sign-ups later in the range (the business is growing)
        signup = date(2023, 6, 1) + timedelta(days=int(span * rng.random() ** 0.8))
        if segment == "Consumer":
            first, last = rng.choice(FIRST), rng.choice(LAST)
            name = f"{first} {last}"
            email = f"{first}.{last}{cid}@example.com".lower()
        else:
            name = f"{rng.choice(BIZ_A)} {rng.choice(BIZ_B)} {rng.choice(BIZ_C)}"
            email = f"purchasing{cid}@example.org"
        phone = f"+1-555-{rng.randint(100, 999):03d}-{rng.randint(1000, 9999):04d}"
        customers.append((cid, name, segment, country, region_ids[region], signup, email, phone))
    tables["customers"] = customers

    # How often each customer orders. Businesses order more often; a few customers are whales.
    activity = [
        (c, rng.paretovariate(2.2) * {"Consumer": 1.0, "Small Business": 2.4, "Enterprise": 4.0}[c[2]])
        for c in customers
    ]
    region_names = {rid: name for name, rid in region_ids.items()}

    orders, items = [], []
    order_id, item_id = 10_000, 0
    total_days = (END - START).days + 1
    for d in range(total_days):
        day = START + timedelta(days=d)
        years = d / 365.25
        weekday = (1.0, 1.0, 1.02, 1.04, 1.08, 1.12, 0.9)[day.weekday()]
        black_friday = day.month == 11 and 22 <= day.day <= 30
        expected = 24 * scale * (1.13 ** years) * SEASONALITY[day.month - 1] * weekday * (1.5 if black_friday else 1)
        eligible = [(c, w * (1 + REGION_GROWTH[region_names[c[4]]]) ** years) for c, w in activity if c[5] <= day]
        if not eligible:
            continue
        n_orders = _poisson(rng, expected)
        buyers = rng.choices([c for c, _ in eligible], weights=[w for _, w in eligible], k=n_orders)
        for cust in buyers:
            order_id += 1
            segment = cust[2]
            channel = _pick(rng, CHANNELS[segment])
            rep = rng.choice(reps_by_region[cust[4]]) if segment != "Consumer" or channel == "Partner" else None
            n_lines = rng.choices((1, 2, 3, 4), weights=(0.55, 0.28, 0.12, 0.05))[0]
            refund_risk = 0.0
            lines = []
            for _ in range(n_lines):
                ci = _category_for(rng, day, years)
                pool = [p for p in by_category[ci] if p[6] <= day and not (p[7] and day >= stop_selling[p[0]])]
                if not pool:
                    continue
                prod = rng.choice(pool)
                qty = 1 if segment == "Consumer" else rng.choice((1, 1, 2, 3, 5, 10) if segment == "Small Business" else (2, 5, 10, 20, 25, 50))
                if CATEGORIES[ci - 1].name == "Accessories" and rng.random() < 0.3:
                    qty += rng.randint(1, 3)  # cables and chargers come in twos and threes
                price = prod[4] * (1.05 if day.year >= 2026 else 1.0)  # list prices rose 5% in January 2026
                discount = _discount(rng, segment, qty, black_friday)
                item_id += 1
                lines.append((item_id, order_id, prod[0], qty, round(price, 2), discount))
                refund_risk += 0.06 if ci == 6 else 0.025  # cameras get returned more
            if not lines:
                order_id -= 1
                continue
            r = rng.random()
            status = "cancelled" if r < 0.045 else "refunded" if r < 0.045 + refund_risk / len(lines) else "completed"
            shipping = 0.0 if channel != "Online" or sum(l[3] * l[4] for l in lines) > 100 else rng.choice((4.99, 6.99, 9.99))
            orders.append((order_id, cust[0], rep, day, channel, status, shipping))
            items.extend(lines)
    tables["orders"] = orders
    tables["order_items"] = items
    return tables


def _poisson(rng: random.Random, lam: float) -> int:
    # Normal approximation is fine for the ~20-60 orders a day we generate
    return max(0, round(rng.gauss(lam, math.sqrt(lam))))


def _category_for(rng: random.Random, day: date, years: float) -> int:
    weights = []
    for cat in CATEGORIES:
        w = cat.weight * (1 + cat.yearly_growth) ** years
        if cat.name == "Laptops" and day.month in (8, 9):
            w *= 1.6  # back to school
        weights.append(w)
    return rng.choices(range(1, len(CATEGORIES) + 1), weights=weights)[0]


def _discount(rng: random.Random, segment: str, qty: int, black_friday: bool) -> float:
    if black_friday and rng.random() < 0.7:
        return rng.choice((0.15, 0.2, 0.25))
    if segment == "Enterprise":
        return rng.choice((0.1, 0.12, 0.15)) if qty >= 10 else 0.08
    if segment == "Small Business" and qty >= 5:
        return 0.05
    return 0.1 if rng.random() < 0.06 else 0.0


# --- loading ------------------------------------------------------------------------

COLUMNS = {
    "regions": ("region_id", "name"),
    "categories": ("category_id", "name"),
    "products": ("product_id", "sku", "name", "category_id", "list_price", "unit_cost", "launched_on", "discontinued"),
    "sales_reps": ("rep_id", "name", "region_id", "hired_on"),
    "customers": ("customer_id", "name", "segment", "country", "region_id", "signup_date", "email", "phone"),
    "orders": ("order_id", "customer_id", "rep_id", "order_date", "channel", "status", "shipping_cost"),
    "order_items": ("order_item_id", "order_id", "product_id", "quantity", "unit_price", "discount"),
}


def _scalar(conn: psycopg.Connection, query: str, params=()):
    with conn.cursor(row_factory=tuple_row) as cur:
        row = cur.execute(query, params).fetchone()
        return row[0] if row else None


def schema_exists(conn: psycopg.Connection) -> bool:
    return bool(_scalar(conn, "SELECT to_regclass('sales.order_items') IS NOT NULL"))


def seed(conn: psycopg.Connection, *, query_role: str = "sqlchat_reader", seed_value: int = 17,
         scale: float = 1.0, reset: bool = False) -> dict[str, int]:
    """Create the sales schema, load the generated data and set up the query role.

    Runs in the caller's transaction. Returns the row count of each table.
    """
    if reset:
        conn.execute("DROP SCHEMA IF EXISTS sales CASCADE")
    conn.execute(DDL)
    for key, text in COMMENTS.items():
        table, _, column = key.partition(".")
        target = (sql.SQL("COLUMN {}.{}").format(sql.Identifier(SCHEMA, table), sql.Identifier(column))
                  if column else sql.SQL("TABLE {}").format(sql.Identifier(SCHEMA, table)))
        conn.execute(sql.SQL("COMMENT ON {} IS {}").format(target, sql.Literal(text)))

    tables = generate(seed_value, scale=scale)
    counts = {}
    for table, cols in COLUMNS.items():
        stmt = sql.SQL("COPY {} ({}) FROM STDIN").format(
            sql.Identifier(SCHEMA, table), sql.SQL(", ").join(map(sql.Identifier, cols)))
        with conn.cursor().copy(stmt) as copy:
            for row in tables[table]:
                copy.write_row(row)
        counts[table] = len(tables[table])
    conn.execute(INDEXES)
    conn.execute("ANALYZE sales.orders; ANALYZE sales.order_items; ANALYZE sales.customers; ANALYZE sales.products")
    if query_role:
        grant_query_role(conn, query_role)
    log.info("seeded sales schema: %s", counts)
    return counts


def grant_query_role(conn: psycopg.Connection, role: str) -> None:
    """A NOLOGIN role with SELECT on the sales tables, minus the PII columns.

    The app switches to it with SET LOCAL ROLE inside a READ ONLY transaction for every
    generated query, so even SQL that slips past the validator can't write anything or
    read the app's own tables. Roles are cluster-wide; the grants are per database.
    """
    ident = sql.Identifier(role)
    if not _scalar(conn, "SELECT 1 FROM pg_roles WHERE rolname = %s", (role,)):
        try:
            with conn.transaction():
                conn.execute(sql.SQL("CREATE ROLE {} NOLOGIN").format(ident))
        except psycopg.errors.DuplicateObject:
            pass  # created by a concurrent seed in another database
    if not _scalar(conn, "SELECT rolsuper FROM pg_roles WHERE rolname = current_user"):
        # A non-superuser needs membership to SET ROLE to it.
        conn.execute(sql.SQL("GRANT {} TO CURRENT_USER").format(ident))
    conn.execute(sql.SQL("REVOKE ALL ON SCHEMA public FROM {}").format(ident))
    conn.execute(sql.SQL("GRANT USAGE ON SCHEMA sales TO {}").format(ident))
    for table, cols in COLUMNS.items():
        hidden = PII_COLUMNS.get(table, ())
        target = sql.Identifier(SCHEMA, table)
        if hidden:
            visible = sql.SQL(", ").join(sql.Identifier(c) for c in cols if c not in hidden)
            conn.execute(sql.SQL("GRANT SELECT ({}) ON {} TO {}").format(visible, target, ident))
        else:
            conn.execute(sql.SQL("GRANT SELECT ON {} TO {}").format(target, ident))

def extract_text(data=None):
    if data is None:
        return None
    return data