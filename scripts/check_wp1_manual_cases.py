"""Read-only check that frozen WP1 manual cases still target the intended source features."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path

import openpyxl

from profile_online_retail_ii import analyze_row, resolve_columns


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "tests" / "fixtures" / "wp1_manual_cases_v1.json"
WORKBOOK = ROOT / "data" / "raw" / "uci_502" / "online_retail_II.xlsx"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def main() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert manifest["schema_version"] == "wp1-manual-cases-v1"
    assert len(manifest["cases"]) == 10
    assert len({case["case_id"] for case in manifest["cases"]}) == 10
    assert sha256_file(WORKBOOK) == manifest["source_file_sha256"]

    windows: dict[str, list[tuple[str, datetime, datetime]]] = defaultdict(list)
    for case in manifest["cases"]:
        start = datetime.fromisoformat(case["start_inclusive"])
        end = datetime.fromisoformat(case["end_exclusive"])
        assert start.tzinfo is None and end - start == timedelta(hours=1)
        assert start.minute == start.second == start.microsecond == 0
        for role, offset in (("current", timedelta()), ("prior", timedelta(days=7))):
            shifted_start, shifted_end = start - offset, end - offset
            windows[shifted_start.strftime("%Y-%m-%d %H")].append(
                (f"{case['case_id']}:{role}", shifted_start, shifted_end)
            )

    counts: dict[str, Counter] = defaultdict(Counter)
    workbook = openpyxl.load_workbook(WORKBOOK, read_only=True, data_only=True)
    try:
        sheet = workbook[manifest["worksheet"]]
        rows = sheet.iter_rows(values_only=True)
        columns = resolve_columns(next(rows))
        for row in rows:
            record = analyze_row(row, columns, workbook.epoch)
            timestamp = record["invoice_datetime"]
            if timestamp is None:
                continue
            for key, start, end in windows.get(timestamp.strftime("%Y-%m-%d %H"), ()):
                if not start <= timestamp < end:
                    continue
                bucket = counts[key]
                bucket["rows"] += 1
                bucket[record["classification"]] += 1
                if record["classification"] == "sale":
                    if record["customer_id"] is None:
                        bucket["missing_customer_sale"] += 1
                    if record["price"] == 0:
                        bucket["zero_price_sale"] += 1
    finally:
        workbook.close()

    for case in manifest["cases"]:
        current = counts[f"{case['case_id']}:current"]
        focus = case["focus"]
        valid = {
            "routine_sales": current["sale"] > 0 and current["rows"] == current["sale"] and current["missing_customer_sale"] == 0,
            "mixed_cancellation": current["sale"] > 0 and current["cancellation"] > 0,
            "cancellation_only": current["sale"] == 0 and current["cancellation"] > 0,
            "missing_customer": current["sale"] > 0 and current["missing_customer_sale"] == current["sale"],
            "zero_price": current["zero_price_sale"] > 0,
            "other_adjustment": current["other_adjustment"] > 0,
            "invalid_price": current["invalid"] > 0,
            "mixed_exceptions": current["sale"] > 0 and current["cancellation"] > 0 and current["other_adjustment"] > 0,
            "higher_volume": current["rows"] >= 500,
            "empty_window": current["rows"] == 0,
        }[focus]
        assert valid, f"{case['case_id']} no longer satisfies {focus}: {dict(current)}"
        prior = counts[f"{case['case_id']}:prior"]
        print(f"PASS {case['case_id']} {focus}: current_rows={current['rows']} prior_rows={prior['rows']}")
    print("PASS workbook hash, ten unique one-hour cases, feature coverage; no KPI results calculated")


if __name__ == "__main__":
    main()
