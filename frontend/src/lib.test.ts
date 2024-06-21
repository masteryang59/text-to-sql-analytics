import { describe, expect, it } from "vitest";
import { buildChartData, labelEvery, niceTicks } from "./chart/data";
import { formatFull, formatPeriod, formatShort, label, toCsv, unitOf } from "./format";
import { tokenize } from "./sql";
import type { Column } from "./types";

const col = (name: string, kind: Column["kind"] = "number"): Column => ({ name, type: "x", kind });

describe("format", () => {
  it("guesses units from column names", () => {
    expect(unitOf("revenue")).toBe("money");
    expect(unitOf("avg_order_value")).toBe("money");
    expect(unitOf("margin_pct")).toBe("pct");
    expect(unitOf("orders")).toBe("count");
    expect(unitOf("units")).toBe("count");
  });

  it("formats compact and full values", () => {
    expect(formatShort(4_230_000, "money")).toBe("$4.23M");
    expect(formatShort(12_900, "count")).toBe("12.9K");
    expect(formatShort(36.12, "pct")).toBe("36.1%");
    expect(formatFull(1234.5, col("revenue"))).toBe("$1,234.50");
    expect(formatFull(-20, col("gross_profit"))).toBe("-$20");
    expect(formatFull(2025, col("year"))).toBe("2025");
    expect(formatFull(null, col("x"))).toBe("NULL");
  });

  it("labels columns and periods", () => {
    expect(label("avg_order_value")).toBe("Avg order value");
    expect(label("margin_pct")).toBe("Margin %");
    expect(formatPeriod("2025-03-01", "month")).toBe("Mar 25");
    expect(formatPeriod("2025-07-01", "quarter")).toBe("Q3 2025");
    expect(formatPeriod("2026-09-14", "week")).toBe("14 Sep");
    expect(formatPeriod("2026-09-14", "order_date")).toBe("14 Sep 26");
    expect(formatPeriod(2025, "year")).toBe("2025");
  });

  it("escapes CSV", () => {
    const csv = toCsv([col("name", "text"), col("n")], [['Kid "Pro", 2', 1], [null, 2]]);
    expect(csv).toBe('name,n\r\n"Kid ""Pro"", 2",1\r\n,2');
  });
});

describe("chart data", () => {
  it("pivots a series column, biggest series first", () => {
    const columns = [col("month", "date"), col("category", "text"), col("revenue")];
    const rows = [
      ["2025-02-01", "A", 1], ["2025-01-01", "A", 2], ["2025-01-01", "B", 10], ["2025-02-01", "B", 20],
    ];
    const d = buildChartData({ type: "line", x: "month", y: ["revenue"], series: "category" }, columns, rows)!;
    expect(d.x).toEqual(["2025-01-01", "2025-02-01"]); // time order restored
    expect(d.series.map((s) => s.name)).toEqual(["B", "A"]);
    expect(d.series[1].values).toEqual([2, 1]);
  });

  it("leaves gaps as null and keeps bar order as queried", () => {
    const columns = [col("region", "text"), col("channel", "text"), col("revenue")];
    const rows = [["NA", "Online", 5], ["EU", "Online", 3], ["EU", "Retail", 1]];
    const d = buildChartData({ type: "bar", x: "region", y: ["revenue"], series: "channel" }, columns, rows)!;
    expect(d.x).toEqual(["NA", "EU"]);
    expect(d.series.find((s) => s.name === "Retail")!.values).toEqual([null, 1]);
  });

  it("returns null for specs that don't fit", () => {
    expect(buildChartData({ type: "bar", x: "nope", y: ["revenue"], series: null }, [col("revenue")], [[1]])).toBeNull();
  });

  it("makes round ticks that include zero", () => {
    expect(niceTicks(0, 3_800_000)).toEqual([0, 1_000_000, 2_000_000, 3_000_000, 4_000_000]);
    expect(niceTicks(12, 37)).toEqual([0, 10, 20, 30, 40]);
    expect(niceTicks(-5, 10)[0]).toBeLessThanOrEqual(-5);
    expect(labelEvery(36, 600, 64)).toBe(4);
  });
});

describe("sql tokenizer", () => {
  it("round-trips and classifies tokens", () => {
    const sql = "SELECT DATE_TRUNC('month', o.order_date)::date AS m, -- note\n  COUNT(*) FROM sales.orders o LIMIT 5";
    const tokens = tokenize(sql);
    expect(tokens.map((t) => t.text).join("")).toBe(sql);
    const types = (text: string) => tokens.find((t) => t.text === text)?.type;
    expect(types("SELECT")).toBe("keyword");
    expect(types("DATE_TRUNC")).toBe("function");
    expect(types("'month'")).toBe("string");
    expect(types("-- note")).toBe("comment");
    expect(types("5")).toBe("number");
  });

  it("handles quotes inside strings", () => {
    const tokens = tokenize("WHERE p.name = 'Kid''s Tablet'");
    expect(tokens.find((t) => t.type === "string")!.text).toBe("'Kid''s Tablet'");
  });
});

export function classifyIntent(data: unknown): unknown {
  if (!data) return null;
  return data;
}

export function classifyIntent(data: unknown): unknown {
  if (!data) return null;
  return data;
}