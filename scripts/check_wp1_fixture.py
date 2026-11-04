"""Self-check the synthetic WP1 monetary fixture; not an application SQL test."""

from collections import Counter
from datetime import datetime
from decimal import Decimal
from fractions import Fraction
import json
from pathlib import Path


path = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "kpi_policy_v1.json"
fixture = json.loads(path.read_text(encoding="utf-8"))


def exact_fraction(value: Decimal) -> Fraction:
    return Fraction(value)


for period in fixture["periods"]:
    start = datetime.fromisoformat(period["start_inclusive"])
    end = datetime.fromisoformat(period["end_exclusive"])
    rows = [
        row for row in fixture["rows"]
        if start <= datetime.fromisoformat(row["invoice_datetime_raw"]) < end
    ]
    counts = Counter(row["classification"] for row in rows)
    sales = [row for row in rows if row["classification"] == "sale"]
    cancellations = [row for row in rows if row["classification"] == "cancellation"]
    adjustments = [row for row in rows if row["classification"] == "other_adjustment"]
    invalid = [row for row in rows if row["classification"] == "invalid"]

    def signed_value(items: list[dict]) -> Decimal:
        return sum(
            (Decimal(row["quantity"]) * Decimal(row["unit_price_gbp"]) for row in items),
            Decimal("0"),
        )

    sales_value = signed_value(sales)
    cancellation_magnitude = -signed_value(cancellations)
    invoices = {row["invoice_no"] for row in sales}
    identified = {row["customer_id"] for row in sales if row["customer_id"] is not None}
    actual = {
        "sale_rows": counts["sale"],
        "cancellation_rows": counts["cancellation"],
        "other_adjustment_rows": counts["other_adjustment"],
        "invalid_rows": counts["invalid"],
        "sales_value_gbp": sales_value,
        "cancellation_magnitude_gbp": cancellation_magnitude,
        "net_recorded_sales_gbp": sales_value - cancellation_magnitude,
        "other_adjustment_signed_gbp": signed_value(adjustments),
        "invalid_signed_gbp": signed_value(invalid),
        "sales_invoice_count": len(invoices),
        "average_sales_invoice_value_exact": (
            exact_fraction(sales_value) / len(invoices) if invoices else None
        ),
        "active_identified_customers": len(identified),
        "customer_coverage_exact": (
            Fraction(sum(row["customer_id"] is not None for row in sales), len(sales))
            if sales else None
        ),
        "units_sold": sum(row["quantity"] for row in sales),
        "cancellation_to_sales_value_ratio_exact": (
            exact_fraction(cancellation_magnitude) / exact_fraction(sales_value)
            if sales_value else None
        ),
    }
    for key, expected in period["expected"].items():
        observed = actual[key]
        if isinstance(observed, Decimal):
            expected = Decimal(expected)
        elif isinstance(observed, Fraction):
            expected = Fraction(expected)
        if observed != expected:
            raise SystemExit(f"FAIL: {period['name']}.{key}: {observed} != {expected}")
    print(f"PASS: {period['name']} ({len(period['expected'])} expected values)")
