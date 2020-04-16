"""A rule-based question parser, so the app works without a language model.

It understands the questions a dashboard answers: one or more measures (revenue,
orders, units, average order value, customers, gross profit, margin, refund rate ...),
grouped by dimensions (category, product, region, country, segment, channel, sales rep,
customer) and/or a time grain, filtered by values it finds in the question ("in Europe",
"for Laptops") and a period ("Q3 2025", "last 90 days", "2024 vs 2025"), ranked with
"top 5" or "which ... most". Follow-ups ("now by region", "only online") are merged
with the previous question.

Anything else (joins it has no template for, "customers who bought X and Y", medians,
growth rates) gets an honest "I can't answer that offline" instead of a guess. The
evaluation (scripts/evaluate.py) measures how often it answers and how often it's right.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from datetime import date, timedelta

from .catalog import Catalog
from .llm import Draft, Request

REV = "oi.quantity * oi.unit_price * (1 - oi.discount)"
PROFIT = "oi.quantity * (oi.unit_price * (1 - oi.discount) - p.unit_cost)"


@dataclass(frozen=True)
class Metric:
    key: str
    alias: str
    expr: str
    needs: frozenset
    label: str
    additive: bool = True  # can be shown as a share of the total
    all_statuses: bool = False  # a rate over all orders, not just completed ones
    base: str = "orders"  # "orders" or "customers"


def _m(key, alias, expr, needs, label, **kw) -> Metric:
    return Metric(key, alias, expr, frozenset(needs), label, **kw)


METRICS = {
    "revenue": _m("revenue", "revenue", f"ROUND(SUM({REV}), 2)", {"oi"}, "revenue"),
    "units": _m("units", "units", "SUM(oi.quantity)", {"oi"}, "units sold"),
    "orders": _m("orders", "orders", "COUNT(DISTINCT o.order_id)", set(), "number of orders"),
    "aov": _m("aov", "avg_order_value",
              f"ROUND(SUM({REV}) / NULLIF(COUNT(DISTINCT o.order_id), 0), 2)", {"oi"},
              "average order value", additive=False),
    "buyers": _m("buyers", "customers", "COUNT(DISTINCT o.customer_id)", set(), "customers who ordered",
                 additive=False),
    "profit": _m("profit", "gross_profit", f"ROUND(SUM({PROFIT}), 2)", {"oi", "p"}, "gross profit"),
    "margin": _m("margin", "margin_pct", f"ROUND(100 * SUM({PROFIT}) / NULLIF(SUM({REV}), 0), 1)",
                 {"oi", "p"}, "gross margin", additive=False),
    "discounts": _m("discounts", "discount_amount",
                    "ROUND(SUM(oi.quantity * oi.unit_price * oi.discount), 2)", {"oi"}, "discounts given"),
    "avg_discount": _m("avg_discount", "avg_discount_pct", "ROUND(100 * AVG(oi.discount), 1)", {"oi"},
                       "average discount per order line", additive=False),
    "refund_rate": _m("refund_rate", "refunded_pct",
                      "ROUND(100.0 * COUNT(DISTINCT o.order_id) FILTER (WHERE o.status = 'refunded')"
                      " / NULLIF(COUNT(DISTINCT o.order_id), 0), 1)",
                      set(), "share of orders refunded", additive=False, all_statuses=True),
    "cancel_rate": _m("cancel_rate", "cancelled_pct",
                      "ROUND(100.0 * COUNT(DISTINCT o.order_id) FILTER (WHERE o.status = 'cancelled')"
                      " / NULLIF(COUNT(DISTINCT o.order_id), 0), 1)",
                      set(), "share of orders cancelled", additive=False, all_statuses=True),
    "accounts": _m("accounts", "customers", "COUNT(*)", set(), "customer accounts", base="customers"),
    "new_customers": _m("new_customers", "new_customers", "COUNT(*)", set(), "new customers (sign-ups)",
                        base="customers"),
}

# Checked in this order; each match is blanked out of the text so "average order value"
# doesn't also count as "orders".
METRIC_PATTERNS = (
    ("aov", r"average order (?:value|size)|avg\.? order value|\baov\b|average (?:basket|spend per order)"),
    ("margin", r"(?:gross |profit )?margins?(?: %| percent(?:age)?)?"),
    ("profit", r"(?:gross )?profits?"),
    ("refund_rate", r"refund rate|return rate|(?:share|percent(?:age)?|%|proportion|rate) of (?:orders )?(?:that (?:were|got) )?(?:refunded|returned)"),
    ("cancel_rate", r"cancell?ation rate|(?:share|percent(?:age)?|%|proportion|rate) of (?:orders )?(?:that (?:were|got) )?cancell?ed"),
    ("avg_discount", r"average discount(?: rate| percent(?:age)?)?"),
    ("discounts", r"(?:total |amount of )?discounts?(?: given| amount| total)?"),
    ("new_customers", r"new customers|new accounts|sign[- ]?ups?|signed up|customers? (?:were )?acquired"),
    ("buyers", r"(?:number of |how many |count of )?(?:unique |distinct |active |paying )?customers (?:who |that )?(?:have )?(?:bought|ordered|purchased|placed (?:an |any )?orders?|made (?:a |an |any )?(?:purchases?|orders?))|(?:unique|distinct|active|paying) customers|(?:number of |how many )buyers|\bbuyers\b"),
    ("accounts", r"how many customers|number of customers|customer count|count of customers|total customers"),
    ("units", r"units?(?: sold)?|quantity(?: sold)?|items sold|how many (?:items|products) (?:were |did we )?sold"),
    ("revenue", r"revenue|\bsales\b|turnover|income|how much (?:money )?(?:did we|we) (?:make|earn|sell)|money"),
    ("orders", r"(?:number of |how many |count of |total )?orders?(?: count)?|purchases"),
)
WEAK_METRICS = {"orders"}  # only used when nothing stronger matched ("revenue from online orders")


@dataclass(frozen=True)
class Dimension:
    key: str
    alias: str
    expr: str
    needs: frozenset
    keyword: str  # regex for the word that names it
    group: tuple[str, ...] = ()  # GROUP BY expressions when not just `expr`


DIMENSIONS = {
    "category": Dimension("category", "category", "c.name", frozenset({"oi", "p", "c"}), r"categor(?:y|ies)"),
    "product": Dimension("product", "product", "p.name", frozenset({"oi", "p"}), r"products?|items?|skus?|models?"),
    "region": Dimension("region", "region", "r.name", frozenset({"cu", "r"}), r"regions?"),
    "country": Dimension("country", "country", "cu.country", frozenset({"cu"}), r"countr(?:y|ies)|markets?"),
    "segment": Dimension("segment", "segment", "cu.segment", frozenset({"cu"}), r"segments?|customer types?"),
    "channel": Dimension("channel", "channel", "o.channel", frozenset(), r"channels?"),
    "rep": Dimension("rep", "sales_rep", "sr.name", frozenset({"sr"}), r"reps?|salesp(?:erson|eople)|account managers?"),
    "customer": Dimension("customer", "customer", "cu.name", frozenset({"cu"}), r"customers?|clients?|accounts?",
                          group=("cu.customer_id", "cu.name")),
}
# Dimensions available when counting customer accounts rather than orders
CUSTOMER_DIMENSIONS = {"region", "country", "segment"}

GRAINS = {
    "day": r"daily|by day|per day|each day|day by day|every day",
    "week": r"weekly|by week|per week|each week|week by week|every week|week over week",
    "month": r"monthly|by month|per month|each month|month by month|every month|month over month|\bmom\b|trend|over time",
    "quarter": r"quarterly|by quarter|per quarter|each quarter|every quarter|quarter over quarter|\bqoq\b",
    "year": r"yearly|annual(?:ly)?|by year|per year|each year|every year|year over year|\byoy\b|year by year",
}

ALIASES = {
    "country": {"United States": ("us", "usa", "u.s.", "u.s.a.", "america", "united states of america"),
                "United Kingdom": ("uk", "u.k.", "britain", "great britain", "england")},
    "region": {"North America": ("na", "north american"), "Europe": ("eu", "european", "emea"),
               "Asia Pacific": ("apac", "asia-pacific", "asia"), "Latin America": ("latam", "south america")},
    "segment": {"Consumer": ("consumers", "individuals", "b2c"),
                "Small Business": ("small businesses", "smb", "smbs", "small business customers"),
                "Enterprise": ("enterprises", "enterprise customers", "large accounts")},
}

OUT_OF_SCOPE = (
    (r"\b(?:inventory|stock levels?|in stock|out of stock|warehouses?)\b", "stock or inventory"),
    (r"\b(?:employees?|staff|salar(?:y|ies)|payroll|headcount)\b", "employees or salaries"),
    (r"\b(?:budgets?|marketing|ad spend|advertising|campaigns?)\b", "marketing or budgets"),
    (r"\b(?:website|web traffic|traffic|visits|visitors|sessions|clicks|conversion rate)\b", "website traffic"),
    (r"\b(?:forecast|predict|projection|next (?:week|month|quarter|year)|tomorrow)\b", "the future (it only holds past orders)"),
    (r"\b(?:reviews?|ratings?|satisfaction|nps|complaints?)\b", "reviews or satisfaction"),
    (r"\b(?:suppliers?|vendors?|competitors?)\b", "suppliers or competitors"),
    (r"\b(?:weather|temperature)\b", "the weather"),
    (r"\b(?:shipping|delivery|deliveries|freight)\b", "shipping in a way this parser can answer"),
)
# Question shapes the templates can't express. Declining beats a confident wrong answer.
UNSUPPORTED = (
    (r"\bmedian\b|\bpercentiles?\b", "medians or percentiles"),
    (r"\b(?:more|fewer|less) than \d+|\bat (?:least|most) \d+|\bover \d+ (?:orders|times|purchases)",
     "conditions on counts per customer or product"),
    (r"\bnever\b|\bwithout (?:any )?(?:orders|sales|purchases)\b|\bno (?:orders|sales)\b",
     "finding things that have no orders"),
    (r"\bboth\b|\bas well as\b", "customers or orders that combine several products or categories"),
    (r"\bgrowth\b|\bgrew\b|\bgrow\b|\bincreas(?:e|ed)\b|\bdeclin(?:e|ed)\b|\bdrop(?:ped)?\b|\bchange[ds]?\b",
     "growth rates or changes between periods (it can show the periods side by side)"),
    (r"\blaunched\b|\bhired\b|\bsigned up (?:before|after)\b", "filters on launch, hire or sign-up dates"),
    (r"\brepeat\b|\breturning\b|\bfirst (?:order|purchase)\b|\bonly once\b|\bchurn", "repeat purchases or customer lifecycles"),
    (r"\b(?:units|items|products|lines) per order\b|\baverage number of\b|\bper customer\b",
     "averages per order or per customer other than order value"),
)
PII = r"\b(?:e-?mails?|phone(?: numbers?)?|addresses|address|passwords?)\b"
WRITE = r"^\s*(?:please\s+)?(?:delete|drop|truncate|update|insert|alter|remove|change|modify|create|grant|wipe|erase|reset)\b|\b(?:delete|drop|truncate)\s+(?:all|the|every|table)\b"

FOLLOW_UP = re.compile(
    r"^\s*(?:and|now|what about|how about|ok(?:ay)?|then|also|same|only|just|instead|but|"
    r"break (?:it|that|this) down|split (?:it|that|this)|show (?:it|that|the same|me that)|for|in)\b"
    r"|\binstead\b|\bsame\b|\b(?:it|that|those|these) (?:by|for|per|in)\b",
    re.I,
)
SUPERLATIVE = r"most|highest|best|top|largest|biggest|greatest|leading|least|lowest|worst|smallest|fewest|weakest|bottom|popular"
ASCENDING = re.compile(r"\b(?:least|lowest|worst|smallest|fewest|weakest|bottom)\b")
NUMBER_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
                "nine": 9, "ten": 10, "twelve": 12, "fifteen": 15, "twenty": 20, "a": 1}
MONTHS = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")
MONTH_WORDS = r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sept?(?:ember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
MONTH_RE = f"({MONTH_WORDS})"


@dataclass(frozen=True)
class Period:
    start: date
    end: date  # exclusive
    label: str
    named: bool = True  # "2025", "Q3 2025" read as "in 2025"; relative ones carry their own wording


@dataclass
class Intent:
    metrics: list[str] = field(default_factory=list)
    dims: list[str] = field(default_factory=list)
    grain: str | None = None
    period: Period | None = None
    filters: dict[str, list[str]] = field(default_factory=dict)
    status: str | None = None
    limit: int | None = None
    ascending: bool = False
    rank_by_time: bool = False  # "which month had the most ..." groups by the grain, ranks by the measure
    share: bool = False
    discontinued: bool = False
    years_compared: bool = False
    notes: list[str] = field(default_factory=list)
    # set when a measure was assumed rather than asked for
    assumed_metric: bool = False

    def has_content(self) -> bool:
        return bool(self.metrics or self.dims or self.grain or self.period or self.filters or self.status)


class OfflineGenerator:
    """Implements the Generator protocol without a model."""

    name = "offline-parser"

    def __init__(self, catalog: Catalog):
        self.catalog = catalog
        self._values = _value_index(catalog)

    def generate(self, request: Request) -> Draft:
        refusal = _refusal(request.question)
        if refusal:
            return Draft(sql=None, explanation=refusal)
        today = request.today
        base: Intent | None = None
        for turn in request.history:
            parsed = self.parse(turn.question, today)
            base = merge(base, parsed, turn.question) if base and is_follow_up(turn.question, parsed) else parsed
        intent = self.parse(request.question, today)
        if base and is_follow_up(request.question, intent):
            intent = merge(base, intent, request.question)
        problem = _complete(intent, request.question)
        if problem:
            return Draft(sql=None, explanation=problem)
        try:
            sql = build_sql(intent)
        except Unsupported as exc:
            return Draft(sql=None, explanation=str(exc))
        return Draft(sql=sql, explanation=explain(intent, request))

    def repair(self, request: Request, previous: Draft, error: str) -> Draft | None:
        return None  # the templates are tested against the schema; there's nothing to learn from an error

    # --- parsing -----------------------------------------------------------------

    def parse(self, question: str, today: date) -> Intent:
        text = " " + _normalize(question) + " "
        intent = Intent()

        text = self._parse_filters(text, intent)
        text = _parse_period(text, today, intent)

        found: dict[str, int] = {}
        listed: set[str] = set()  # weak measures named as one of a list: "revenue and orders"
        for key, pattern in METRIC_PATTERNS:
            for m in re.finditer(rf"(?<![a-z]){pattern}(?![a-z])", text):
                found.setdefault(key, m.start())
                if re.search(r"\b(?:and|&)\s*$", text[: m.start()]) or re.match(r"\s*(?:and|&)\b", text[m.end():]):
                    listed.add(key)
                text = _blank(text, m)
        if any(k not in WEAK_METRICS for k in found):
            found = {k: pos for k, pos in found.items() if k not in WEAK_METRICS or k in listed}
        # in the order they were asked for
        intent.metrics = sorted(found, key=found.get)
        if re.search(r"\b(?:best|top)[- ]?sell(?:ing|er)s?\b|\bmost popular\b|\bsold the most\b|\bsells? (?:the )?(?:most|best)\b", text) and not intent.metrics:
            intent.metrics = ["units"]
            intent.notes.append("“Best-selling” is ranked by units sold.")

        for grain, pattern in GRAINS.items():
            if re.search(rf"(?<![a-z])(?:{pattern})(?![a-z])", text):
                intent.grain = grain
        m = re.search(r"\b(?:which|what)\s+(day|week|month|quarter|year)\b", text) or re.search(
            rf"\b(?:{SUPERLATIVE})\s+(day|week|month|quarter|year)\b", text)
        if m:
            intent.grain = m.group(1)
            intent.rank_by_time = True
            intent.limit = 1

        self._parse_dimensions(text, intent)
        self._parse_ranking(text, intent)

        if re.search(r"\b(?:share|percent(?:age)?|%|proportion|contribution|split|mix)\b(?! of orders)", text) and not re.search(r"\bsplit (?:it|that|this|by)\b", text):
            intent.share = True
        if re.search(r"\bdiscontinued\b", text):
            intent.discontinued = True
        return intent

    def _parse_filters(self, text: str, intent: Intent) -> str:
        if re.search(r"\bcancell?ed\b|\bcancell?ations?\b", text):
            intent.status = "cancelled"
        if re.search(r"\brefund(?:ed|s)?\b|\breturn(?:ed|s)\b", text):
            intent.status = "refunded"
        # Longest names first, so "Aero 14 Pro" wins over "Aero 14"
        for alias, (dim, value) in self._values:
            pattern = rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])"
            m = re.search(pattern, text)
            if not m:
                continue
            values = intent.filters.setdefault(dim, [])
            if value not in values:
                values.append(value)
            text = text[: m.start()] + " " * len(alias) + text[m.end():]
        return text

    def _parse_dimensions(self, text: str, intent: Intent) -> None:
        trigger = rf"(?:by|per|for each|each|every|which|what|across|top\s+\w+|bottom\s+\w+|{SUPERLATIVE}|selling|performing|and|vs)"
        found = []
        for key, dim in DIMENSIONS.items():
            for m in re.finditer(rf"\b(?:{trigger})\s+(?:[a-z-]+\s+){{0,2}}?({dim.keyword})\b|\b({dim.keyword})\s+(?:breakdown|ranking|ranked|split|with the)\b", text):
                found.append((m.start(1) if m.group(1) else m.start(2), key, m.group(1) or m.group(2)))
                break
        for _, key, word in sorted(found):
            if key not in intent.dims:
                intent.dims.append(key)
            # "which category ... the most" / "best-selling product" asks for one row
            asks_one = (re.search(rf"\b(?:which|what|the)\s+(?:[a-z-]+\s+){{0,2}}?{re.escape(word)}\b", text)
                        and re.search(rf"\b(?:{SUPERLATIVE})\b", text)) or \
                re.search(rf"\b(?:{SUPERLATIVE}|selling)\s+(?:[a-z-]+\s+)?{re.escape(word)}\b", text)
            if asks_one and not word.endswith("s") and intent.limit is None:
                intent.limit = 1
        # "Online vs Retail revenue": several values of one dimension = compare them
        for dim, values in intent.filters.items():
            if len(values) > 1 and dim not in intent.dims and dim in DIMENSIONS:
                intent.dims.append(dim)

    def _parse_ranking(self, text: str, intent: Intent) -> None:
        m = re.search(r"\b(top|bottom|best|worst|first|highest|lowest|largest|biggest|smallest)\s+(\d{1,3}|"
                      + "|".join(w for w in NUMBER_WORDS if w != "a") + r")\b", text)
        if m:
            n = m.group(2)
            intent.limit = int(n) if n.isdigit() else NUMBER_WORDS[n]
        elif intent.limit is None and intent.dims and re.search(rf"\b(?:{SUPERLATIVE})\b", text):
            intent.limit = 10
        intent.ascending = bool(ASCENDING.search(text))


class Unsupported(ValueError):
    pass


def is_follow_up(question: str, intent: Intent) -> bool:
    if FOLLOW_UP.search(question):
        return True
    # "in 2025?" / "for Europe" alone: a filter without a measure or grouping
    return not intent.metrics and not intent.dims and not intent.grain and intent.has_content()


def merge(base: Intent, new: Intent, question: str) -> Intent:
    q = question.lower()
    out = replace(base, filters={k: list(v) for k, v in base.filters.items()}, notes=list(new.notes))
    if new.metrics:
        out.metrics = list(new.metrics)
        out.assumed_metric = new.assumed_metric
    if new.dims:
        if re.search(r"\b(?:also|too|as well|and by)\b", q):
            out.dims = base.dims + [d for d in new.dims if d not in base.dims]
        else:
            out.dims = list(new.dims)
            if re.search(r"\binstead\b", q) and not new.grain:
                out.grain = None
                out.rank_by_time = False
        out.limit = new.limit
    elif new.limit is not None:
        out.limit = new.limit
    if new.grain:
        out.grain, out.rank_by_time = new.grain, new.rank_by_time
    if new.period:
        out.period, out.years_compared = new.period, new.years_compared
    for dim, values in new.filters.items():
        out.filters[dim] = list(values)
    if re.search(r"\b(?:all|every|any) (?:regions?|categor(?:y|ies)|channels?|countr(?:y|ies)|segments?)\b|\bremove the filter\b", q):
        out.filters = {}
    if new.status:
        out.status = new.status
    out.share = new.share or (base.share and not new.metrics)
    out.discontinued = new.discontinued or base.discontinued
    if new.ascending:
        out.ascending = True
    return out


def _complete(intent: Intent, question: str) -> str | None:
    """Fill in a default measure, or explain why the question can't be answered."""
    if not intent.metrics:
        ranked_or_trend = intent.grain or intent.limit or re.search(
            r"\b(?:perform|doing|did|sell|sold|best|worst|top|compare|breakdown|split|trend)", question.lower())
        if intent.dims and ranked_or_trend or intent.grain:
            intent.metrics = ["revenue"]
            intent.assumed_metric = True
        elif intent.status and (intent.period or intent.filters or intent.dims or "how many" in question.lower()):
            intent.metrics = ["orders"]
        else:
            return ("The offline parser couldn't work out what to measure. Try something like “revenue by "
                    "category last quarter” or “top 5 products by units in 2025”, or connect a language model "
                    "(OPENAI_API_KEY or OPENAI_BASE_URL) for open-ended questions.")
    customer_base = [k for k in intent.metrics if METRICS[k].base == "customers"]
    if customer_base and len(customer_base) != len(intent.metrics):
        return "The offline parser can't combine customer sign-ups with order measures in one query."
    if customer_base:
        bad = [d for d in intent.dims if d not in CUSTOMER_DIMENSIONS]
        bad += [d for d in intent.filters if d not in CUSTOMER_DIMENSIONS]
        if bad:
            return f"The offline parser can count customer accounts by region, country or segment, not by {bad[0]}."
        if intent.status:
            return "Customer accounts don't have an order status."
    return None


def _refusal(question: str) -> str | None:
    q = _normalize(question)
    if re.search(WRITE, q):
        return "I can only read the sales data. I can't change, add or delete anything."
    if re.search(PII, q):
        return "Customers' contact details (email, phone, address) are personal data and can't be queried here."
    for pattern, what in OUT_OF_SCOPE:
        if re.search(pattern, q):
            return f"The sales database has no data about {what}. It holds orders, order lines, products, customers, regions and sales reps."
    for pattern, what in UNSUPPORTED:
        if re.search(pattern, q):
            return (f"The offline parser can't answer questions about {what}. Connect a language model "
                    f"(OPENAI_API_KEY or OPENAI_BASE_URL) for questions like this, or write the SQL in the editor.")
    return None


# --- periods --------------------------------------------------------------------------

def _month_start(d: date) -> date:
    return d.replace(day=1)


def _add_months(d: date, n: int) -> date:
    y, m = divmod(d.month - 1 + n, 12)
    return date(d.year + y, m + 1, 1)


def _quarter_start(d: date) -> date:
    return date(d.year, 3 * ((d.month - 1) // 3) + 1, 1)


def _fmt(d: date) -> str:
    return f"{d.day} {d.strftime('%b')} {d.year}"


def _span_label(start: date, end: date) -> str:
    return f"{_fmt(start)} – {_fmt(end - timedelta(days=1))}"


def _month_num(word: str) -> int:
    return MONTHS.index(word[:3]) + 1


def _period_of(text: str, today: date) -> tuple[date, date, str] | None:
    """A single period phrase: '2025', 'q3 2025', 'march 2026', 'h1 2025'."""
    text = text.strip()
    m = re.fullmatch(r"q([1-4])(?:\s+(?:of\s+)?(\d{4}))?", text)
    if m:
        year = int(m.group(2) or today.year)
        start = date(year, 3 * int(m.group(1)) - 2, 1)
        if not m.group(2) and start > today:
            start = start.replace(year=year - 1)
        return start, _add_months(start, 3), f"Q{m.group(1)} {start.year}"
    m = re.fullmatch(r"h([12])(?:\s+(?:of\s+)?(\d{4}))?", text)
    if m:
        year = int(m.group(2) or today.year)
        start = date(year, 1 if m.group(1) == "1" else 7, 1)
        return start, _add_months(start, 6), f"H{m.group(1)} {year}"
    m = re.fullmatch(MONTH_RE + r"(?:\s+(?:of\s+)?(\d{4}))?", text)
    if m:
        month = _month_num(m.group(1))
        year = int(m.group(2)) if m.group(2) else (today.year if month <= today.month else today.year - 1)
        start = date(year, month, 1)
        return start, _add_months(start, 1), start.strftime("%B %Y")
    m = re.fullmatch(r"(\d{4})", text)
    if m and 2000 <= int(m.group(1)) <= 2099:
        year = int(m.group(1))
        return date(year, 1, 1), date(year + 1, 1, 1), str(year)
    return None


ORDINAL_QUARTER = {"first": 1, "1st": 1, "second": 2, "2nd": 2, "third": 3, "3rd": 3, "fourth": 4, "4th": 4, "last": 4}
UNIT_RE = r"(days?|weeks?|months?|quarters?|years?)"
PERIOD_RE = rf"(?:q[1-4](?:\s+(?:of\s+)?\d{{4}})?|h[12](?:\s+(?:of\s+)?\d{{4}})?|{MONTH_WORDS}(?:\s+(?:of\s+)?\d{{4}})?|\d{{4}})"


def _blank(text: str, m: re.Match) -> str:
    return text[: m.start()] + " " * (m.end() - m.start()) + text[m.end():]


def _parse_period(text: str, today: date, intent: Intent) -> str:
    tomorrow = today + timedelta(days=1)
    # "first quarter of 2025" -> "q1 2025", "first half of 2025" -> "h1 2025"
    text = re.sub(r"\b(first|1st|second|2nd|third|3rd|fourth|4th)\s+quarter(?:\s+of)?\s+(\d{4})\b",
                  lambda m: f"q{ORDINAL_QUARTER[m.group(1)]} {m.group(2)}".ljust(len(m.group(0))), text)
    text = re.sub(r"\b(first|second)\s+half(?:\s+of)?\s+(\d{4})\b",
                  lambda m: f"h{1 if m.group(1) == 'first' else 2} {m.group(2)}".ljust(len(m.group(0))), text)

    def done(start: date, end: date, label: str, m: re.Match, named: bool = True) -> str:
        intent.period = Period(start, min(end, tomorrow) if start <= today else end, label, named)
        return _blank(text, m)

    m = re.search(rf"\b(?:between|from)\s+({PERIOD_RE})\s+(?:and|to|until|through|thru|-)\s+({PERIOD_RE})\b", text)
    if m:
        a, b = _period_of(m.group(1), today), _period_of(m.group(2), today)
        if a and b:
            return done(a[0], b[1], f"{a[2]} to {b[2]}", m)
    m = re.search(rf"\bsince\s+({PERIOD_RE})\b", text)
    if m:
        a = _period_of(m.group(1), today)
        if a:
            return done(a[0], tomorrow, f"since {a[2]} (through {_fmt(today)})", m, named=False)
    m = re.search(rf"\b(?:last|past|previous|trailing)\s+(\d+|{'|'.join(NUMBER_WORDS)})\s+{UNIT_RE}\b", text)
    if m:
        n = int(m.group(1)) if m.group(1).isdigit() else NUMBER_WORDS[m.group(1)]
        unit = m.group(2).rstrip("s")
        if unit == "day":
            start = tomorrow - timedelta(days=n)
        elif unit == "week":
            start = tomorrow - timedelta(weeks=n)
        else:
            months = n * {"month": 1, "quarter": 3, "year": 12}[unit]
            start = _add_months(tomorrow, -months) if tomorrow.day == 1 else _shift_months(tomorrow, -months)
        return done(start, tomorrow, f"in the last {n} {unit}{'s' if n != 1 else ''} ({_span_label(start, tomorrow)})", m, named=False)
    m = re.search(r"\b(?:year to date|ytd|so far this year)\b", text)
    if m:
        start = date(today.year, 1, 1)
        return done(start, tomorrow, f"year to date ({_span_label(start, tomorrow)})", m, named=False)
    m = re.search(r"\b(last|previous|past|this|current)\s+(week|month|quarter|year)\b", text)
    if m:
        which, unit = m.group(1), m.group(2)
        if unit == "week":
            this_start = today - timedelta(days=today.weekday())
            start = this_start if which in ("this", "current") else this_start - timedelta(weeks=1)
            end = start + timedelta(weeks=1)
        elif unit == "month":
            this_start = _month_start(today)
            start = this_start if which in ("this", "current") else _add_months(this_start, -1)
            end = _add_months(start, 1)
        elif unit == "quarter":
            this_start = _quarter_start(today)
            start = this_start if which in ("this", "current") else _add_months(this_start, -3)
            end = _add_months(start, 3)
        else:
            start = date(today.year - (0 if which in ("this", "current") else 1), 1, 1)
            end = date(start.year + 1, 1, 1)
        label = f"{which} {unit} ({_span_label(start, min(end, tomorrow))})"
        return done(start, end, label, m, named=False)
    m = re.search(r"\b(today|yesterday)\b", text)
    if m:
        day = today if m.group(1) == "today" else today - timedelta(days=1)
        return done(day, day + timedelta(days=1), f"{m.group(1)} ({_fmt(day)})", m, named=False)

    m = re.search(r"\b(q[1-4]|h[12])(?:\s+(?:of\s+)?(\d{4}))?\b", text)
    if m:
        p = _period_of(m.group(0), today)
        if p:
            return done(*p, m)
    # Month names need a year or a preposition, so "may" in "may I see" doesn't count
    m = re.search(rf"\b{MONTH_RE}\s+(?:of\s+)?(\d{{4}})\b", text) or re.search(
        rf"\b(?:in|during|for|of)\s+{MONTH_RE}\b", text)
    if m:
        month_word = m.group(1)
        year = m.group(2) if m.lastindex and m.lastindex >= 2 else None
        p = _period_of(f"{month_word} {year}" if year else month_word, today)
        if p:
            return done(*p, m)

    years = sorted({int(y) for y in re.findall(r"\b(20\d{2})\b", text)})
    if len(years) == 1:
        m = re.search(rf"\b{years[0]}\b", text)
        return done(date(years[0], 1, 1), date(years[0] + 1, 1, 1), str(years[0]), m)
    if len(years) > 1:
        intent.period = Period(date(years[0], 1, 1), date(years[-1] + 1, 1, 1),
                               " vs ".join(map(str, years)) if len(years) <= 3 else f"{years[0]}–{years[-1]}")
        intent.years_compared = len(years) == 2 or bool(re.search(r"\b(?:vs|versus|compared?|against)\b", text))
        for y in years:
            text = re.sub(rf"\b{y}\b", "    ", text)
    return text


def _shift_months(d: date, n: int) -> date:
    y, m = divmod(d.month - 1 + n, 12)
    year, month = d.year + y, m + 1
    last_day = (_add_months(date(year, month, 1), 1) - timedelta(days=1)).day
    return date(year, month, min(d.day, last_day))


# --- SQL ------------------------------------------------------------------------------

JOINS = {
    "oi": "JOIN sales.order_items oi ON oi.order_id = o.order_id",
    "p": "JOIN sales.products p ON p.product_id = oi.product_id",
    "c": "JOIN sales.categories c ON c.category_id = p.category_id",
    "cu": "JOIN sales.customers cu ON cu.customer_id = o.customer_id",
    "r": "JOIN sales.regions r ON r.region_id = cu.region_id",
    "sr": "JOIN sales.sales_reps sr ON sr.rep_id = o.rep_id",
}
REQUIRES = {"p": {"oi"}, "c": {"p", "oi"}, "r": {"cu"}}


def _quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def build_sql(intent: Intent) -> str:
    metrics = [METRICS[k] for k in intent.metrics]
    customer_base = metrics[0].base == "customers"
    date_col = "cu.signup_date" if customer_base else "o.order_date"

    needs: set[str] = set()
    select: list[str] = []
    group: list[str] = []
    where: list[str] = []

    grain = intent.grain
    if intent.years_compared and not grain:
        grain = "year"
    if grain:
        expr = (f"EXTRACT(YEAR FROM {date_col})::int" if grain == "year"
                else f"DATE_TRUNC('{grain}', {date_col})::date")
        select.append(f"{expr} AS {grain}")
        group.append(expr)
    for key in intent.dims:
        dim = DIMENSIONS[key]
        needs |= dim.needs
        select.append(f"{dim.expr} AS {dim.alias}")
        group.extend(dim.group or (dim.expr,))
    for m in metrics:
        needs |= m.needs
        select.append(f"{m.expr} AS {m.alias}")
    if intent.share and (intent.dims or grain):
        first = next((m for m in metrics if m.additive), None)
        if first:
            inner = first.expr.removeprefix("ROUND(").rsplit(", 2)", 1)[0] if first.expr.startswith("ROUND(") else first.expr
            select.append(f"ROUND(100.0 * {inner} / NULLIF(SUM({inner}) OVER (), 0), 1) AS {first.alias}_share_pct")

    for dim_key, values in intent.filters.items():
        dim = DIMENSIONS[dim_key]
        needs |= dim.needs
        vals = ", ".join(_quote(v) for v in values)
        where.append(f"{dim.expr} = {vals}" if len(values) == 1 else f"{dim.expr} IN ({vals})")
    if intent.discontinued:
        if customer_base:
            raise Unsupported("The offline parser can't filter customer accounts by product.")
        needs |= {"oi", "p"}
        where.append("p.discontinued")
    if not customer_base:
        if intent.status:
            if not any(m.all_statuses for m in metrics):
                where.insert(0, f"o.status = '{intent.status}'")
        elif not all(m.all_statuses for m in metrics):
            where.insert(0, "o.status = 'completed'")
    if intent.period:
        where.append(f"{date_col} >= DATE '{intent.period.start.isoformat()}'")
        where.append(f"{date_col} < DATE '{intent.period.end.isoformat()}'")

    for alias in list(needs):
        needs |= REQUIRES.get(alias, set())
    if customer_base:
        from_lines = ["FROM sales.customers cu"]
        if "r" in needs:
            from_lines.append("JOIN sales.regions r ON r.region_id = cu.region_id")
    else:
        from_lines = ["FROM sales.orders o"] + [JOINS[a] for a in JOINS if a in needs]

    order: list[str] = []
    direction = "ASC" if intent.ascending else "DESC"
    measure = metrics[0].alias
    if grain and not intent.rank_by_time:
        order.append("1")
        if intent.dims:
            order.append(f"{measure} {direction}")
    else:
        order.append(f"{measure} {direction}")
        if intent.dims or grain:
            order.append("1")

    lines = ["SELECT " + ",\n       ".join(select)]
    lines += from_lines
    if where:
        lines.append("WHERE " + "\n  AND ".join(where))
    if group:
        lines.append("GROUP BY " + ", ".join(group))
        lines.append("ORDER BY " + ", ".join(order))
    if intent.limit and (intent.dims or intent.rank_by_time):
        lines.append(f"LIMIT {intent.limit}")
    return "\n".join(lines)


def explain(intent: Intent, request: Request) -> str:
    metrics = [METRICS[k] for k in intent.metrics]
    what = _join([m.label for m in metrics])
    what = what[0].upper() + what[1:]
    grain = intent.grain or ("year" if intent.years_compared else None)
    extreme = "lowest" if intent.ascending else "highest"
    one_winner = intent.limit == 1 and len(intent.dims) == 1 and not grain
    if one_winner:
        noun = DIMENSIONS[intent.dims[0]].alias.replace("_", " ")
        parts = [f"{noun[0].upper()}{noun[1:]} with the {extreme} {metrics[0].label}"]
    else:
        parts = [what]
    if intent.rank_by_time:
        parts.append(f"for the {grain} with the {extreme} {metrics[0].label}")
    elif grain:
        parts.append(f"per {grain}")
    if intent.dims and not one_winner:
        parts.append("by " + _join([DIMENSIONS[d].alias.replace("_", " ") for d in intent.dims]))
    if intent.filters:
        parts.append("for " + _join([" or ".join(v) for v in intent.filters.values()]))
    if intent.discontinued:
        parts.append("for discontinued products")
    if intent.period:
        parts.append(f"in {intent.period.label}" if intent.period.named else intent.period.label)
    if intent.limit and intent.dims and not intent.rank_by_time and not one_winner:
        parts.append(f"({'bottom' if intent.ascending else 'top'} {intent.limit})")
    sentence = " ".join(parts) + "."

    notes = []
    if intent.assumed_metric:
        notes.append("No measure was named, so this shows revenue.")
    if metrics[0].base == "orders":
        if any(m.all_statuses for m in metrics):
            notes.append("Rates are over all orders, including cancelled and refunded ones.")
        elif intent.status:
            notes.append(f"Only {intent.status} orders.")
        else:
            notes.append("Completed orders only.")
        if any(k in ("revenue", "aov", "profit", "margin") for k in intent.metrics):
            notes.append("Revenue is after discounts and excludes shipping.")
    if intent.share:
        notes.append("Share is of the total across the rows shown before any LIMIT.")
    notes.extend(intent.notes)
    if not intent.period and request.data_start and request.data_end:
        notes.append(f"All dates in the data ({_fmt(request.data_start)} – {_fmt(request.data_end)}).")
    return " ".join([sentence, *notes])


def _join(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def _normalize(question: str) -> str:
    q = question.lower().replace("’", "'").replace("–", "-")
    q = re.sub(r"\bsales\s+reps?\b|\bsales\s*(?:people|persons?)\b", "rep", q)
    q = re.sub(r"\bsales channels?\b", "channel", q)
    q = re.sub(r"\bproduct\s+categor(y|ies)\b", r"categor\1", q)
    q = re.sub(r"\bcustomer\s+(?:segments?|types?)\b", "segment", q)
    q = re.sub(r"[?!,;:()\"]", " ", q)
    return re.sub(r"\s+", " ", q).strip()


def _value_index(catalog: Catalog) -> list[tuple[str, tuple[str, str]]]:
    """(lower-case text to look for, (dimension, value)), longest first."""
    entries: dict[str, tuple[str, str]] = {}
    for dim, values in catalog.dimension_values.items():
        for value in values:
            low = value.lower()
            entries.setdefault(low, (dim, value))
            if dim == "category":
                singular = low[:-3] + "y" if low.endswith("ies") else low[:-1] if low.endswith("s") else low
                entries.setdefault(singular, (dim, value))
                entries.setdefault(singular + "s" if not singular.endswith("s") else singular, (dim, value))
            for alias in ALIASES.get(dim, {}).get(value, ()):
                entries.setdefault(alias, (dim, value))
    # Channel and segment words also appear in phrases like "online orders" - that's the point.
    return sorted(entries.items(), key=lambda kv: -len(kv[0]))

def transcode_video(data=None):
    if data is None:
        return None
    return data