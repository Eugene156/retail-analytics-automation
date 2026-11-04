"""Profile the complete UCI Online Retail II workbook without modifying it.

The output contains aggregate evidence only. It intentionally excludes raw rows,
customer identifiers, product descriptions, and invoice identifiers.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter, defaultdict
from datetime import date, datetime, time, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import openpyxl
from openpyxl.utils.datetime import from_excel


PUBLISHER_ROW_COUNT = 1_067_371
SOURCE_URL = "https://archive.ics.uci.edu/dataset/502/online+retail+ii"
DOWNLOAD_URL = (
    "https://archive.ics.uci.edu/static/public/502/online%2Bretail%2Bii.zip"
)

COLUMN_ALIASES = {
    "invoice_no": {"invoice", "invoiceno"},
    "stock_code": {"stockcode"},
    "description": {"description"},
    "quantity": {"quantity"},
    "invoice_datetime": {"invoicedate", "invoicedatetime"},
    "unit_price_gbp": {"price", "unitprice", "unitpricegbp"},
    "customer_id": {"customerid"},
    "country": {"country"},
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workbook", required=True, type=Path)
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def normalize_header(value: Any) -> str:
    return "".join(character for character in str(value).lower() if character.isalnum())


def resolve_columns(headers: list[Any]) -> dict[str, int]:
    normalized = [normalize_header(value) for value in headers]
    resolved: dict[str, int] = {}
    for canonical, aliases in COLUMN_ALIASES.items():
        matches = [index for index, value in enumerate(normalized) if value in aliases]
        if len(matches) != 1:
            raise ValueError(
                f"Expected one column for {canonical!r}; found {len(matches)} in {headers!r}"
            )
        resolved[canonical] = matches[0]
    return resolved


def value_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, datetime):
        return "datetime"
    if isinstance(value, date):
        return "date"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "str"
    return type(value).__name__


def is_missing(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def to_decimal(value: Any) -> tuple[Decimal | None, str | None]:
    if value is None or isinstance(value, bool):
        return None, "missing_or_non_numeric"
    try:
        if isinstance(value, Decimal):
            result = value
        elif isinstance(value, int):
            result = Decimal(value)
        elif isinstance(value, float):
            if not math.isfinite(value):
                return None, "non_finite"
            result = Decimal(str(value))
        elif isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return None, "missing_or_non_numeric"
            result = Decimal(stripped)
        else:
            return None, "missing_or_non_numeric"
    except InvalidOperation:
        return None, "missing_or_non_numeric"
    if not result.is_finite():
        return None, "non_finite"
    return result, None


def to_datetime(value: Any, epoch: datetime) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, time.min)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            converted = from_excel(value, epoch=epoch)
            if isinstance(converted, datetime):
                return converted
            if isinstance(converted, date):
                return datetime.combine(converted, time.min)
        except (OverflowError, TypeError, ValueError):
            return None
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        for parser in (
            datetime.fromisoformat,
            lambda text: datetime.strptime(text, "%Y-%m-%d %H:%M:%S"),
            lambda text: datetime.strptime(text, "%m/%d/%Y %H:%M"),
            lambda text: datetime.strptime(text, "%d/%m/%Y %H:%M"),
        ):
            try:
                return parser(stripped)
            except ValueError:
                continue
    return None


def fingerprint_value(value: Any) -> tuple[str, str]:
    kind = value_type(value)
    if isinstance(value, (datetime, date)):
        rendered = value.isoformat()
    elif isinstance(value, float):
        rendered = repr(value)
    elif value is None:
        rendered = ""
    else:
        rendered = str(value)
    return kind, rendered


def row_fingerprint(values: tuple[Any, ...]) -> bytes:
    payload = json.dumps(
        [fingerprint_value(value) for value in values],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.blake2b(payload, digest_size=16).digest()


def new_profile(headers: list[str]) -> dict[str, Any]:
    return {
        "headers": headers,
        "row_count": 0,
        "completely_blank_rows": 0,
        "null_counts": Counter(),
        "blank_string_counts": Counter(),
        "type_counts": {header: Counter() for header in headers},
        "min_invoice_datetime": None,
        "max_invoice_datetime": None,
        "classification_counts": Counter(),
        "classification_value_gbp": defaultdict(Decimal),
        "classification_value_calculable_rows": Counter(),
        "invalid_reason_counts": Counter(),
        "other_adjustment_reason_counts": Counter(),
        "retention_flag_counts": Counter(),
        "retention_flag_value_gbp": defaultdict(Decimal),
        "distinct_invoice_no": set(),
        "distinct_stock_code": set(),
        "distinct_customer_id": set(),
        "distinct_country": set(),
    }


def analyze_row(
    row: tuple[Any, ...], columns: dict[str, int], epoch: datetime
) -> dict[str, Any]:
    invoice = row[columns["invoice_no"]]
    stock_code = row[columns["stock_code"]]
    description = row[columns["description"]]
    quantity_raw = row[columns["quantity"]]
    invoice_datetime_raw = row[columns["invoice_datetime"]]
    price_raw = row[columns["unit_price_gbp"]]
    customer_id = row[columns["customer_id"]]
    country = row[columns["country"]]

    quantity, quantity_error = to_decimal(quantity_raw)
    price, price_error = to_decimal(price_raw)
    invoice_datetime = to_datetime(invoice_datetime_raw, epoch)
    invalid_reasons: list[str] = []
    if is_missing(invoice):
        invalid_reasons.append("missing_invoice")
    if is_missing(stock_code):
        invalid_reasons.append("missing_stock_code")
    if invoice_datetime is None:
        invalid_reasons.append("invalid_or_missing_invoice_datetime")
    if quantity_error:
        invalid_reasons.append(f"quantity_{quantity_error}")
    if price_error:
        invalid_reasons.append(f"unit_price_{price_error}")
    elif price is not None and price < 0:
        invalid_reasons.append("negative_unit_price")

    money = quantity * price if quantity is not None and price is not None else None
    invoice_text = "" if invoice is None else str(invoice).strip()
    is_cancellation_invoice = invoice_text.upper().startswith("C")

    if invalid_reasons:
        classification = "invalid"
        other_adjustment_reason = None
    elif quantity == 0:
        classification = "zero_quantity_non_sales"
        other_adjustment_reason = None
    elif is_cancellation_invoice and quantity is not None and quantity < 0:
        classification = "cancellation"
        other_adjustment_reason = None
    elif not is_cancellation_invoice and quantity is not None and quantity > 0:
        classification = "sale"
        other_adjustment_reason = None
    else:
        classification = "other_adjustment"
        if is_cancellation_invoice:
            other_adjustment_reason = "cancellation_invoice_non_negative_quantity"
        else:
            other_adjustment_reason = "negative_quantity_without_cancellation_invoice"

    canonical_values = tuple(row[columns[name]] for name in COLUMN_ALIASES)
    return {
        "invoice": invoice,
        "stock_code": stock_code,
        "description": description,
        "invoice_datetime": invoice_datetime,
        "customer_id": customer_id,
        "country": country,
        "quantity": quantity,
        "price": price,
        "money": money,
        "classification": classification,
        "other_adjustment_reason": other_adjustment_reason,
        "invalid_reasons": invalid_reasons,
        "canonical_values": canonical_values,
    }


def update_profile(
    profile: dict[str, Any],
    row: tuple[Any, ...],
    record: dict[str, Any],
) -> None:
    profile["row_count"] += 1
    if all(is_missing(value) for value in row):
        profile["completely_blank_rows"] += 1

    for index, header in enumerate(profile["headers"]):
        value = row[index] if index < len(row) else None
        profile["type_counts"][header][value_type(value)] += 1
        if value is None:
            profile["null_counts"][header] += 1
        elif isinstance(value, str) and not value.strip():
            profile["blank_string_counts"][header] += 1

    invoice_datetime = record["invoice_datetime"]
    if invoice_datetime is not None:
        current_min = profile["min_invoice_datetime"]
        current_max = profile["max_invoice_datetime"]
        if current_min is None or invoice_datetime < current_min:
            profile["min_invoice_datetime"] = invoice_datetime
        if current_max is None or invoice_datetime > current_max:
            profile["max_invoice_datetime"] = invoice_datetime

    classification = record["classification"]
    profile["classification_counts"][classification] += 1
    money = record["money"]
    if money is not None:
        profile["classification_value_gbp"][classification] += money
        profile["classification_value_calculable_rows"][classification] += 1
    for reason in record["invalid_reasons"]:
        profile["invalid_reason_counts"][reason] += 1
    if record["other_adjustment_reason"]:
        profile["other_adjustment_reason_counts"][
            record["other_adjustment_reason"]
        ] += 1

    invoice = record["invoice"]
    stock_code = record["stock_code"]
    customer_id = record["customer_id"]
    country = record["country"]
    if not is_missing(invoice):
        profile["distinct_invoice_no"].add(str(invoice))
    if not is_missing(stock_code):
        profile["distinct_stock_code"].add(str(stock_code))
    if not is_missing(customer_id):
        profile["distinct_customer_id"].add(str(customer_id))
    if not is_missing(country):
        profile["distinct_country"].add(str(country))

    missing_customer = is_missing(customer_id)
    missing_description = is_missing(record["description"])
    if missing_customer:
        profile["retention_flag_counts"]["missing_customer_all_rows"] += 1
        if classification != "invalid":
            profile["retention_flag_counts"]["missing_customer_valid_rows"] += 1
        if classification == "sale":
            profile["retention_flag_counts"]["missing_customer_sale_rows"] += 1
            if money is not None:
                profile["retention_flag_value_gbp"][
                    "missing_customer_sale_value_gbp"
                ] += money
    if missing_description:
        profile["retention_flag_counts"]["missing_description_all_rows"] += 1
        if classification != "invalid":
            profile["retention_flag_counts"]["missing_description_valid_rows"] += 1
    if classification == "sale" and record["price"] == 0:
        profile["retention_flag_counts"]["zero_price_sale_rows"] += 1
        if money is not None:
            profile["retention_flag_value_gbp"]["zero_price_sale_value_gbp"] += money


def update_duplicate_stats(
    fingerprints: dict[bytes, int], stats: Counter[str], fingerprint: bytes
) -> None:
    new_count = fingerprints.get(fingerprint, 0) + 1
    fingerprints[fingerprint] = new_count
    if new_count == 2:
        stats["duplicate_value_groups"] += 1
        stats["duplicate_rows_beyond_first"] += 1
    elif new_count > 2:
        stats["duplicate_rows_beyond_first"] += 1


def merge_profiles(target: dict[str, Any], source: dict[str, Any]) -> None:
    target["row_count"] += source["row_count"]
    target["completely_blank_rows"] += source["completely_blank_rows"]
    target["null_counts"].update(source["null_counts"])
    target["blank_string_counts"].update(source["blank_string_counts"])
    for header, counts in source["type_counts"].items():
        if header not in target["type_counts"]:
            target["type_counts"][header] = Counter()
        target["type_counts"][header].update(counts)
    source_min = source["min_invoice_datetime"]
    source_max = source["max_invoice_datetime"]
    if source_min is not None and (
        target["min_invoice_datetime"] is None
        or source_min < target["min_invoice_datetime"]
    ):
        target["min_invoice_datetime"] = source_min
    if source_max is not None and (
        target["max_invoice_datetime"] is None
        or source_max > target["max_invoice_datetime"]
    ):
        target["max_invoice_datetime"] = source_max
    target["classification_counts"].update(source["classification_counts"])
    target["classification_value_calculable_rows"].update(
        source["classification_value_calculable_rows"]
    )
    for key, value in source["classification_value_gbp"].items():
        target["classification_value_gbp"][key] += value
    target["invalid_reason_counts"].update(source["invalid_reason_counts"])
    target["other_adjustment_reason_counts"].update(
        source["other_adjustment_reason_counts"]
    )
    target["retention_flag_counts"].update(source["retention_flag_counts"])
    for key, value in source["retention_flag_value_gbp"].items():
        target["retention_flag_value_gbp"][key] += value
    for key in (
        "distinct_invoice_no",
        "distinct_stock_code",
        "distinct_customer_id",
        "distinct_country",
    ):
        target[key].update(source[key])


def decimal_text(value: Decimal) -> str:
    return format(value, "f")


def finalize_profile(
    profile: dict[str, Any], duplicate_stats: Counter[str]
) -> dict[str, Any]:
    return {
        "headers": profile["headers"],
        "row_count": profile["row_count"],
        "physical_source_row_identities": profile["row_count"],
        "completely_blank_rows": profile["completely_blank_rows"],
        "null_counts": {
            header: profile["null_counts"].get(header, 0)
            for header in profile["headers"]
        },
        "blank_string_counts": {
            header: profile["blank_string_counts"].get(header, 0)
            for header in profile["headers"]
        },
        "type_counts": {
            header: dict(sorted(counts.items()))
            for header, counts in profile["type_counts"].items()
        },
        "min_invoice_datetime": (
            profile["min_invoice_datetime"].isoformat(sep=" ")
            if profile["min_invoice_datetime"]
            else None
        ),
        "max_invoice_datetime": (
            profile["max_invoice_datetime"].isoformat(sep=" ")
            if profile["max_invoice_datetime"]
            else None
        ),
        "classification_counts": {
            key: profile["classification_counts"].get(key, 0)
            for key in (
                "sale",
                "cancellation",
                "other_adjustment",
                "zero_quantity_non_sales",
                "invalid",
            )
        },
        "classification_signed_value_gbp": {
            key: decimal_text(value)
            for key, value in sorted(profile["classification_value_gbp"].items())
        },
        "classification_value_calculable_rows": dict(
            sorted(profile["classification_value_calculable_rows"].items())
        ),
        "invalid_reason_counts": dict(
            sorted(profile["invalid_reason_counts"].items())
        ),
        "other_adjustment_reason_counts": dict(
            sorted(profile["other_adjustment_reason_counts"].items())
        ),
        "retention_flag_counts": dict(
            sorted(profile["retention_flag_counts"].items())
        ),
        "retention_flag_signed_value_gbp": {
            key: decimal_text(value)
            for key, value in sorted(profile["retention_flag_value_gbp"].items())
        },
        "distinct_counts": {
            "invoice_no": len(profile["distinct_invoice_no"]),
            "stock_code": len(profile["distinct_stock_code"]),
            "customer_id_non_null": len(profile["distinct_customer_id"]),
            "country_non_null": len(profile["distinct_country"]),
        },
        "duplicate_detection": {
            "method": "BLAKE2b-128 over typed canonical values in the eight mapped fields",
            "duplicate_value_groups": duplicate_stats["duplicate_value_groups"],
            "duplicate_rows_beyond_first": duplicate_stats[
                "duplicate_rows_beyond_first"
            ],
            "rows_removed": 0,
        },
    }


def main() -> int:
    args = parse_args()
    workbook_path = args.workbook.resolve(strict=True)
    archive_path = args.archive.resolve(strict=True)
    output_path = args.output.resolve()
    started_at = datetime.now(timezone.utc)

    print(f"Opening workbook read-only: {workbook_path}", flush=True)
    workbook = openpyxl.load_workbook(
        workbook_path, read_only=True, data_only=True, keep_links=False
    )
    global_profile: dict[str, Any] | None = None
    global_fingerprints: dict[bytes, int] = {}
    global_duplicate_stats: Counter[str] = Counter()
    worksheet_results: list[dict[str, Any]] = []
    worksheet_fingerprint_counts: list[tuple[str, dict[bytes, int]]] = []

    try:
        for worksheet in workbook.worksheets:
            print(f"Profiling worksheet: {worksheet.title}", flush=True)
            rows = worksheet.iter_rows(values_only=True)
            try:
                raw_headers = list(next(rows))
            except StopIteration as error:
                raise ValueError(f"Worksheet {worksheet.title!r} is empty") from error
            headers = ["" if value is None else str(value) for value in raw_headers]
            columns = resolve_columns(raw_headers)
            sheet_profile = new_profile(headers)
            if global_profile is None:
                global_profile = new_profile(headers)
            sheet_fingerprints: dict[bytes, int] = {}
            sheet_duplicate_stats: Counter[str] = Counter()

            for physical_row_number, raw_row in enumerate(rows, start=2):
                row = tuple(raw_row)
                record = analyze_row(row, columns, workbook.epoch)
                update_profile(sheet_profile, row, record)
                fingerprint = row_fingerprint(record["canonical_values"])
                update_duplicate_stats(
                    sheet_fingerprints, sheet_duplicate_stats, fingerprint
                )
                update_duplicate_stats(
                    global_fingerprints, global_duplicate_stats, fingerprint
                )
                if sheet_profile["row_count"] % 100_000 == 0:
                    print(
                        f"  {worksheet.title}: {sheet_profile['row_count']:,} rows",
                        flush=True,
                    )

            merge_profiles(global_profile, sheet_profile)
            sheet_result = finalize_profile(sheet_profile, sheet_duplicate_stats)
            sheet_result["worksheet"] = worksheet.title
            sheet_result["worksheet_max_row_reported"] = worksheet.max_row
            sheet_result["worksheet_max_column_reported"] = worksheet.max_column
            worksheet_results.append(sheet_result)
            worksheet_fingerprint_counts.append(
                (worksheet.title, sheet_fingerprints)
            )
            print(
                f"Completed {worksheet.title}: {sheet_profile['row_count']:,} rows",
                flush=True,
            )
    finally:
        workbook.close()

    if global_profile is None:
        raise ValueError("Workbook has no worksheets")

    completed_at = datetime.now(timezone.utc)
    global_result = finalize_profile(global_profile, global_duplicate_stats)
    global_result["publisher_row_count"] = PUBLISHER_ROW_COUNT
    global_result["row_count_matches_publisher"] = (
        global_result["row_count"] == PUBLISHER_ROW_COUNT
    )

    cross_worksheet_value_overlaps: list[dict[str, Any]] = []
    for left_index, (left_name, left_counts) in enumerate(
        worksheet_fingerprint_counts
    ):
        for right_name, right_counts in worksheet_fingerprint_counts[left_index + 1 :]:
            if len(left_counts) <= len(right_counts):
                common = [key for key in left_counts if key in right_counts]
            else:
                common = [key for key in right_counts if key in left_counts]
            cross_worksheet_value_overlaps.append(
                {
                    "left_worksheet": left_name,
                    "right_worksheet": right_name,
                    "matching_value_groups": len(common),
                    "matched_row_occurrences_per_side": sum(
                        min(left_counts[key], right_counts[key]) for key in common
                    ),
                    "left_row_occurrences_in_matching_groups": sum(
                        left_counts[key] for key in common
                    ),
                    "right_row_occurrences_in_matching_groups": sum(
                        right_counts[key] for key in common
                    ),
                    "rows_removed": 0,
                }
            )

    result = {
        "profile_schema_version": "1.0",
        "generated_at_utc": completed_at.isoformat(),
        "elapsed_seconds": round((completed_at - started_at).total_seconds(), 3),
        "tooling": {
            "python": __import__("sys").version.split()[0],
            "openpyxl": openpyxl.__version__,
            "mode": "read_only_data_only",
        },
        "source": {
            "publisher": "UCI Machine Learning Repository",
            "dataset": "Online Retail II",
            "dataset_id": 502,
            "metadata_url": SOURCE_URL,
            "download_url": DOWNLOAD_URL,
            "license": "CC BY 4.0",
            "archive_filename": archive_path.name,
            "archive_size_bytes": archive_path.stat().st_size,
            "archive_sha256": sha256_file(archive_path),
            "workbook_filename": workbook_path.name,
            "workbook_size_bytes": workbook_path.stat().st_size,
            "workbook_sha256": sha256_file(workbook_path),
        },
        "workbook": {
            "worksheet_count": len(worksheet_results),
            "worksheets": worksheet_results,
            "cross_worksheet_value_overlaps": cross_worksheet_value_overlaps,
        },
        "reconciliation": global_result,
        "safety": {
            "source_modified": False,
            "raw_rows_written_to_profile": False,
            "identical_value_rows_removed": 0,
        },
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"Profile written: {output_path}", flush=True)
    print(
        f"Reconciled rows: {global_result['row_count']:,}; "
        f"publisher match: {global_result['row_count_matches_publisher']}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
