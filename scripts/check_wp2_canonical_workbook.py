"""Independently reconcile canonical SQL periods against the pinned XLSX.

The workbook is opened read-only. Output contains aggregate values only.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from fractions import Fraction
import json
from pathlib import Path
import subprocess
import sys

import openpyxl

from profile_online_retail_ii import analyze_row, is_missing, resolve_columns, sha256_file, to_datetime


ROOT = Path(__file__).resolve().parents[1]
WORKBOOK = ROOT / "data" / "raw" / "uci_502" / "online_retail_II.xlsx"
HASH = "BCBE73B35F5B7BABF197FB0CB983A11F5D9FF929078D4AA53D171B1F2DF2E980"
SOURCE_BYTES = 45_622_278
SHEETS = {"Year 2009-2010": 525_461, "Year 2010-2011": 541_910}
HEADERS = (
    "Invoice", "StockCode", "Description", "Quantity", "InvoiceDate",
    "Price", "Customer ID", "Country",
)
CUTOVER = datetime(2010, 12, 1)
START = datetime(2010, 11, 30)
END = datetime(2010, 12, 2)
MANIFEST = ROOT / "tests" / "fixtures" / "wp1_manual_cases_v1.json"
CONTAINER = "raa-g0-postgres-1"
DATABASE = "raa_wp2_validation"
COMPARISON_RULE = "the same one-hour window exactly seven calendar days earlier, on the same worksheet"
CHANGE_FIELDS = (
    "sales_value_gbp", "cancellation_magnitude_gbp", "net_recorded_sales_gbp",
    "sales_invoice_count", "active_identified_customers", "units_sold",
)


@dataclass(frozen=True)
class Period:
    name: str
    start: datetime
    end: datetime


@dataclass
class Bucket:
    counts: Counter[str] = field(default_factory=Counter)
    signed: defaultdict[str, Decimal] = field(
        default_factory=lambda: defaultdict(lambda: Decimal(0))
    )
    sale_invoices: set[str] = field(default_factory=set)
    identified_customers: set[str] = field(default_factory=set)
    units_sold: Decimal = Decimal(0)


def periods_for(case_ids: list[str]) -> list[Period]:
    if len(set(case_ids)) != len(case_ids):
        raise ValueError("Period IDs must be unique")
    if not case_ids:
        raise ValueError("At least one period ID is required")
    periods = {"cross_cutover": Period("cross_cutover", START, END)}
    if any(case_id != "cross_cutover" for case_id in case_ids):
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        if (manifest.get("schema_version") != "wp1-manual-cases-v1"
                or manifest.get("source_file_sha256") != HASH
                or manifest.get("worksheet") != "Year 2010-2011"
                or manifest.get("comparison_rule") != COMPARISON_RULE):
            raise ValueError("Frozen WP1 case manifest does not match the pinned source")
        for case in manifest["cases"]:
            start = datetime.fromisoformat(case["start_inclusive"])
            end = datetime.fromisoformat(case["end_exclusive"])
            if (start.tzinfo is not None or end.tzinfo is not None
                    or end - start != timedelta(hours=1) or start < CUTOVER):
                raise ValueError("WP1 case has an unsupported period or worksheet")
            if case["case_id"] in periods:
                raise ValueError("Duplicate WP1 case ID")
            periods[case["case_id"]] = Period(case["case_id"], start, end)
    try:
        return [periods[case_id] for case_id in case_ids]
    except KeyError as error:
        raise ValueError(f"Unknown period ID: {error.args[0]}") from error


def prior_periods_for(periods: list[Period]) -> list[Period]:
    if any(period.name == "cross_cutover" or period.start - timedelta(days=7) < CUTOVER
           for period in periods):
        raise ValueError("Comparison reconciliation supports frozen WP1 windows only")
    return [Period(period.name + "_prior", period.start - timedelta(days=7),
                   period.end - timedelta(days=7)) for period in periods]


def selected_sheet(sheet_name: str, timestamp: datetime) -> bool:
    return (sheet_name == "Year 2009-2010" and timestamp < CUTOVER) or (
        sheet_name == "Year 2010-2011" and timestamp >= CUTOVER
    )


def add_record(bucket: Bucket, record: dict) -> None:
    classification = record["classification"]
    bucket.counts["period_source_rows"] += 1
    bucket.counts[classification] += 1
    value = record["money"]
    if value is not None:
        bucket.signed[classification] += value
        if classification == "invalid":
            bucket.counts["invalid_value_calculable_rows"] += 1
    if classification == "sale":
        bucket.sale_invoices.add(str(record["invoice"]).strip())
        bucket.units_sold += record["quantity"]
        customer = record["customer_id"]
        if is_missing(customer):
            bucket.counts["missing_customer_sale_rows"] += 1
        else:
            bucket.identified_customers.add(str(customer).strip())
        if record["price"] == 0:
            bucket.counts["zero_price_sale_rows"] += 1


def finalize(bucket: Bucket) -> dict[str, int | Decimal | Fraction | None]:
    counts = bucket.counts
    signed = bucket.signed
    sales_value = signed["sale"]
    cancellation_magnitude = -signed["cancellation"]
    sale_rows = counts["sale"]
    invoice_count = len(bucket.sale_invoices)
    return {
        "period_source_rows": counts["period_source_rows"],
        "sale_rows": sale_rows,
        "cancellation_rows": counts["cancellation"],
        "other_adjustment_rows": counts["other_adjustment"],
        "zero_quantity_rows": counts["zero_quantity_non_sales"],
        "invalid_rows": counts["invalid"],
        "sales_value_gbp": sales_value,
        "cancellation_magnitude_gbp": cancellation_magnitude,
        "net_recorded_sales_gbp": sales_value - cancellation_magnitude,
        "other_adjustment_signed_gbp": signed["other_adjustment"],
        "invalid_signed_gbp": signed["invalid"],
        "invalid_value_calculable_rows": counts["invalid_value_calculable_rows"],
        "sales_invoice_count": invoice_count,
        "average_sales_invoice_value_exact": (
            Fraction(sales_value) / invoice_count if invoice_count else None
        ),
        "active_identified_customers": len(bucket.identified_customers),
        "missing_customer_sale_rows": counts["missing_customer_sale_rows"],
        "customer_coverage_exact": (
            Fraction(sale_rows - counts["missing_customer_sale_rows"], sale_rows)
            if sale_rows else None
        ),
        "units_sold": bucket.units_sold,
        "zero_price_sale_rows": counts["zero_price_sale_rows"],
        "cancellation_to_sales_value_ratio_exact": (
            Fraction(cancellation_magnitude) / Fraction(sales_value)
            if sales_value else None
        ),
    }


def workbook_metrics(periods: list[Period]) -> tuple[dict[str, dict], dict[str, int]]:
    if not WORKBOOK.is_file() or WORKBOOK.stat().st_size != SOURCE_BYTES:
        raise ValueError("Pinned source workbook is missing or has the wrong byte size")
    if sha256_file(WORKBOOK) != HASH:
        raise ValueError("Pinned source workbook SHA-256 differs")

    buckets = {period.name: Bucket() for period in periods}
    sheet_rows: dict[str, int] = {}
    workbook = openpyxl.load_workbook(WORKBOOK, read_only=True, data_only=True)
    try:
        if workbook.sheetnames != list(SHEETS):
            raise ValueError("Annual worksheet names/order differ")
        for sheet_name, expected_rows in SHEETS.items():
            rows = workbook[sheet_name].iter_rows(values_only=True)
            headers = tuple(next(rows))
            if headers != HEADERS:
                raise ValueError("Source worksheet headers differ")
            columns = resolve_columns(list(headers))
            physical_rows = 0
            for source_row_number, row in enumerate(rows, start=2):
                physical_rows += 1
                timestamp = to_datetime(row[columns["invoice_datetime"]], workbook.epoch)
                if timestamp is None:
                    raise ValueError(
                        f"Undated source row cannot be reconciled: {sheet_name} row {source_row_number}"
                    )
                if not selected_sheet(sheet_name, timestamp):
                    continue
                matches = [period.name for period in periods if period.start <= timestamp < period.end]
                if matches:
                    record = analyze_row(row, columns, workbook.epoch)
                    for name in matches:
                        add_record(buckets[name], record)
            if physical_rows != expected_rows:
                raise ValueError(f"{sheet_name}: expected {expected_rows} source rows, got {physical_rows}")
            sheet_rows[sheet_name] = physical_rows
    finally:
        workbook.close()

    return {name: finalize(bucket) for name, bucket in buckets.items()}, sheet_rows


def sql_json(query: str) -> dict:
    command = [
        "docker", "exec", CONTAINER, "psql", "-X", "-q", "-A", "-t",
        "-v", "ON_ERROR_STOP=1", "-U", "g0_user", "-d", DATABASE, "-c",
        "BEGIN READ ONLY; " + query + "; ROLLBACK;",
    ]
    completed = subprocess.run(command, text=True, capture_output=True, check=False)
    if completed.returncode:
        raise RuntimeError(completed.stderr.strip() or "Read-only SQL query failed")
    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    if len(lines) != 1:
        raise ValueError("Expected exactly one canonical SQL result")
    return json.loads(lines[0], parse_float=Decimal)


def sql_metrics(period: Period) -> dict[str, int | Decimal | None]:
    return sql_json(
        "SELECT row_to_json(k)::text FROM retail.canonical_period_kpis_v1("
        f"'{HASH}', '{period.start:%Y-%m-%d %H:%M:%S}', "
        f"'{period.end:%Y-%m-%d %H:%M:%S}') k"
    )


def sql_report(period: Period) -> dict:
    return sql_json(
        "SELECT retail.deterministic_comparison_report_v1("
        f"'{HASH}', '{period.start:%Y-%m-%d %H:%M:%S}', "
        f"'{period.end:%Y-%m-%d %H:%M:%S}', "
        f"'{period.end:%Y-%m-%d %H:%M:%S}')::text"
    )


def compare(independent: dict, observed: dict) -> None:
    if set(independent) != set(observed):
        raise ValueError("Workbook/SQL KPI field sets differ")
    ratio_fields = {
        "average_sales_invoice_value_exact",
        "customer_coverage_exact",
        "cancellation_to_sales_value_ratio_exact",
    }
    for field, expected in independent.items():
        actual = observed[field]
        if expected is None:
            valid = actual is None
        elif field in ratio_fields:
            valid = actual is not None and abs(
                Fraction(Decimal(str(actual))) - expected
            ) <= Fraction(1, 10**12)
        else:
            valid = actual is not None and Decimal(str(actual)) == Decimal(str(expected))
        if not valid:
            raise ValueError(f"{field}: workbook={expected}, SQL={actual}")


def headline_changes(current: dict, prior: dict) -> dict:
    changes = {}
    for metric_id in CHANGE_FIELDS:
        current_value = current[metric_id]
        prior_value = prior[metric_id]
        delta = current_value - prior_value
        changes[metric_id] = {
            "current_value": current_value,
            "prior_value": prior_value,
            "absolute_change": delta,
            "relative_change": Fraction(delta) / abs(Fraction(prior_value)) if prior_value else None,
            "relative_change_status": "available" if prior_value else "zero_baseline",
        }
    return changes


def compare_report(period: Period, prior_period: Period, current: dict,
                   prior: dict, observed: dict) -> None:
    metadata = {
        "schema_version": "deterministic-comparison-report-v1",
        "comparison_rule": "same-window-seven-calendar-days-earlier",
        "relative_change_formula": "(current-prior)/abs(prior)",
        "source_time_interpretation": "naive workbook time",
    }
    for key, expected in metadata.items():
        if observed.get(key) != expected:
            raise ValueError(f"Comparison metadata differs: {key}")
    for key, selected, expected_kpis in (
        ("current_period", period, current), ("prior_period", prior_period, prior),
    ):
        report = observed[key]
        expected_header = {
            "schema_version": "deterministic-period-report-v1",
            "source_file_sha256": HASH,
            "policy_version": "v1",
            "period_start_inclusive": selected.start.isoformat(timespec="microseconds"),
            "period_end_exclusive": selected.end.isoformat(timespec="microseconds"),
            "source_as_of_exclusive": period.end.isoformat(timespec="microseconds"),
        }
        if any(report.get(field) != value for field, value in expected_header.items()):
            raise ValueError(f"Period provenance or cutoff differs: {key}")
        compare(expected_kpis, report["kpis"])

    expected_changes = headline_changes(current, prior)
    if set(observed["changes"]) != set(expected_changes):
        raise ValueError("Comparison metric IDs differ")
    for metric_id, expected in expected_changes.items():
        actual = observed["changes"][metric_id]
        if set(actual) != set(expected):
            raise ValueError(f"Change fields differ: {metric_id}")
        for field, value in expected.items():
            if field == "relative_change" and value is not None:
                valid = actual[field] is not None and abs(
                    Fraction(Decimal(str(actual[field]))) - value
                ) <= Fraction(1, 10**12)
            else:
                valid = actual[field] == value
            if not valid:
                raise ValueError(f"Change differs: {metric_id}.{field}")


def json_number(value):
    return str(value) if isinstance(value, (Decimal, Fraction)) else value


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--compare-sql", action="store_true")
    modes.add_argument("--compare-report", action="store_true",
                       help="Check current/prior KPIs and six changes in migration 011")
    parser.add_argument("--case-ids", nargs="+", default=["cross_cutover"],
                        help="cross_cutover and/or frozen WP1 IDs such as M02 M07 M10")
    args = parser.parse_args()
    periods = periods_for(args.case_ids)
    priors = prior_periods_for(periods) if args.compare_report else []
    independent, sheet_rows = workbook_metrics(periods + priors)
    for index, period in enumerate(periods):
        if args.compare_report:
            compare_report(period, priors[index], independent[period.name],
                           independent[priors[index].name], sql_report(period))
            print(f"PASS|{period.name}|current-kpis=20|prior-kpis=20|changes=6", file=sys.stderr, flush=True)
        if args.compare_sql:
            try:
                compare(independent[period.name], sql_metrics(period))
            except (ValueError, RuntimeError) as error:
                raise ValueError(f"{period.name}: {error}") from error

    output = {
        "source_sha256": HASH,
        "worksheet_rows_read": sheet_rows,
        "periods": [{
            "period_id": period.name,
            "period_start_inclusive": period.start.isoformat(),
            "period_end_exclusive": period.end.isoformat(),
            "independent_xlsx_metrics": {
                key: json_number(value)
                for key, value in independent[period.name].items()
            },
            "sql_comparison": "PASS" if args.compare_sql or args.compare_report else "NOT_RUN",
        } for period in periods],
    }
    if args.compare_report:
        output["comparison_reports"] = [{
            "case_id": period.name,
            "prior_start_inclusive": priors[index].start.isoformat(),
            "prior_end_exclusive": priors[index].end.isoformat(),
            "independent_prior_xlsx_metrics": {
                key: json_number(value)
                for key, value in independent[priors[index].name].items()
            },
            "independent_changes": {
                key: {field: json_number(value) for field, value in change.items()}
                for key, change in headline_changes(
                    independent[period.name], independent[priors[index].name]
                ).items()
            },
            "comparison_report_check": "PASS",
        } for index, period in enumerate(periods)]
    print(json.dumps(output, indent=2, ensure_ascii=True))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, RuntimeError) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        raise SystemExit(1)
