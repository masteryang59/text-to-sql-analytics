from sqlchat.charts import choose_chart, infer_chart
from sqlchat.executor import ResultColumn as C

NUM = "number"


def col(name, kind):
    return C(name, "x", kind)


def test_single_value_is_a_number():
    assert infer_chart([col("revenue", NUM)], [[123.4]])["type"] == "number"
    # a label next to it still reads as one number
    assert infer_chart([col("category", "text"), col("margin_pct", NUM)], [["Cameras", 36.1]])["type"] == "number"


def test_time_series_is_a_line():
    cols = [col("month", "date"), col("revenue", NUM), col("orders", NUM)]
    chart = infer_chart(cols, [["2025-01-01", 1, 2], ["2025-02-01", 3, 4]])
    # revenue and orders have different units, so only the first is plotted
    assert chart == {"type": "line", "x": "month", "y": ["revenue"], "series": None}


def test_time_series_with_a_category_is_one_line_per_value():
    cols = [col("month", "date"), col("category", "text"), col("revenue", NUM)]
    rows = [[m, c, 1] for m in ("2025-01-01", "2025-02-01") for c in ("A", "B", "C")]
    assert infer_chart(cols, rows)["series"] == "category"


def test_too_many_series_means_no_chart():
    cols = [col("month", "date"), col("product", "text"), col("revenue", NUM)]
    rows = [[m, f"p{i}", 1] for m in ("2025-01-01", "2025-02-01") for i in range(20)]
    assert infer_chart(cols, rows) is None


def test_few_whole_years_are_bars():
    chart = infer_chart([col("year", NUM), col("revenue", NUM)], [[2024, 1], [2025, 2], [2026, 3]])
    assert chart["type"] == "bar" and chart["x"] == "year"


def test_categories_are_bars_horizontal_when_many_or_long():
    short = infer_chart([col("channel", "text"), col("revenue", NUM)], [["Online", 1], ["Retail", 2]])
    assert short["type"] == "bar" and not short["horizontal"]
    many = infer_chart([col("product", "text"), col("units", NUM)], [[f"Product {i}", i] for i in range(12)])
    assert many["horizontal"]


def test_two_text_columns_make_grouped_bars():
    cols = [col("region", "text"), col("channel", "text"), col("revenue", NUM)]
    rows = [[r, c, 1] for r in ("EU", "NA") for c in ("Online", "Retail")]
    assert infer_chart(cols, rows) == {"type": "bar", "x": "region", "y": ["revenue"], "series": "channel",
                                       "horizontal": False}


def test_percentages_plot_together():
    cols = [col("channel", "text"), col("refunded_pct", NUM), col("cancelled_pct", NUM)]
    assert infer_chart(cols, [["a", 1, 2], ["b", 3, 4]])["y"] == ["refunded_pct", "cancelled_pct"]


def test_no_numbers_no_chart():
    assert infer_chart([col("name", "text")], [["a"], ["b"]]) is None
    assert choose_chart([col("n", NUM)], []) is None


def test_valid_suggestion_is_used():
    cols = [col("region", "text"), col("revenue", NUM)]
    rows = [["EU", 1], ["NA", 2]]
    chart = choose_chart(cols, rows, {"type": "bar", "x": "region", "y": ["revenue"], "series": None})
    assert chart["type"] == "bar" and chart["x"] == "region"


def test_bad_suggestions_fall_back_to_inference():
    cols = [col("month", "date"), col("revenue", NUM)]
    rows = [["2025-01-01", 1], ["2025-02-01", 2]]
    for bad in (
        {"type": "bar", "x": "nope", "y": ["revenue"]},           # unknown column
        {"type": "line", "x": "month", "y": ["month"]},           # y not numeric
        {"type": "pie", "x": "month", "y": ["revenue"]},          # unknown type
        {"type": "number", "x": None, "y": ["revenue"]},          # several rows
        {"type": "line", "x": "month", "y": ["revenue"], "series": "ghost"},
    ):
        assert choose_chart(cols, rows, bad)["type"] == "line", bad


def test_explicit_none_is_respected_for_tables():
    cols = [col("customer", "text"), col("revenue", NUM)]
    assert choose_chart(cols, [["a", 1], ["b", 2]], {"type": "none", "x": None, "y": []}) is None

def dequeue_batch(data=None):
    if data is None:
        return None
    return data