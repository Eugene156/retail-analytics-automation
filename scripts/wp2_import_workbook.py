"""Validation-only, transactional import of the pinned UCI workbook to WP2 SQL.

The XLSX is read-only. Raw cell values never enter terminal output or source
control. This CLI is not the planned FastAPI import contract or production
deployment; it targets the isolated local validation database only.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import subprocess
import time
from uuid import uuid4

import openpyxl

from profile_online_retail_ii import fingerprint_value


ROOT = Path(__file__).resolve().parents[1]
WORKBOOK = ROOT / "data" / "raw" / "uci_502" / "online_retail_II.xlsx"
FINALIZE_SQL = ROOT / "db" / "import_finalize.sql"
CONTAINER = "raa-g0-postgres-1"
DATABASE = "raa_wp2_validation"
EXPECTED_SHA256 = "BCBE73B35F5B7BABF197FB0CB983A11F5D9FF929078D4AA53D171B1F2DF2E980"
EXPECTED_SIZE = 45_622_278
EXPECTED_COUNTS = {"Year 2009-2010": 525_461, "Year 2010-2011": 541_910}
EXPECTED_HEADERS = [
    "Invoice", "StockCode", "Description", "Quantity", "InvoiceDate",
    "Price", "Customer ID", "Country",
]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def copy_rows(stream, writer: csv.writer, table: str, rows) -> None:
    stream.write(f"COPY {table} FROM STDIN WITH (FORMAT csv);\n")
    for row in rows:
        writer.writerow(row)
    stream.write("\\.\n")


def import_workbook(idempotency_key: str) -> None:
    if not idempotency_key or len(idempotency_key) > 120 or "\n" in idempotency_key:
        raise ValueError("Idempotency key must be a nonempty single line of at most 120 characters")
    if WORKBOOK.stat().st_size != EXPECTED_SIZE or sha256_file(WORKBOOK) != EXPECTED_SHA256:
        raise RuntimeError("Pinned source workbook size/hash mismatch; import not started")
    workbook = openpyxl.load_workbook(WORKBOOK, read_only=True, data_only=True)
    if workbook.sheetnames != list(EXPECTED_COUNTS):
        workbook.close()
        raise RuntimeError("Workbook sheets differ from the verified source")

    job_id = str(uuid4())
    process = subprocess.Popen(
        [
            "docker", "exec", "-i", CONTAINER, "psql", "-X", "-q", "-A", "-t",
            "-v", "ON_ERROR_STOP=1", "-U", "g0_user", "-d", DATABASE, "-f", "-",
        ],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", bufsize=1,
    )
    started = time.monotonic()
    counts: dict[str, int] = {}
    try:
        assert process.stdin is not None
        stream = process.stdin
        writer = csv.writer(stream, lineterminator="\n")
        stream.write("BEGIN;\n")
        stream.write(
            "CREATE TEMP TABLE stage_snapshot (source_file_sha256 text, dataset_id text, "
            "source_filename text, source_bytes bigint, source_url text, "
            "license_name text, expected_data_rows bigint) ON COMMIT DROP;\n"
        )
        copy_rows(stream, writer, "stage_snapshot", [[
            EXPECTED_SHA256, "UCI-502", WORKBOOK.name, EXPECTED_SIZE,
            "https://archive.ics.uci.edu/dataset/502/online+retail+ii",
            "CC BY 4.0", sum(EXPECTED_COUNTS.values()),
        ]])
        stream.write(
            "CREATE TEMP TABLE stage_sheets (source_file_sha256 text, worksheet text, "
            "sheet_ordinal integer, original_headers jsonb, expected_data_rows bigint) "
            "ON COMMIT DROP;\n"
        )
        copy_rows(stream, writer, "stage_sheets", [
            [EXPECTED_SHA256, name, ordinal, json.dumps(EXPECTED_HEADERS), expected]
            for ordinal, (name, expected) in enumerate(EXPECTED_COUNTS.items(), start=1)
        ])
        stream.write(
            "CREATE TEMP TABLE stage_job (job_id uuid, idempotency_key text) "
            "ON COMMIT DROP;\n"
        )
        copy_rows(stream, writer, "stage_job", [[job_id, idempotency_key]])
        stream.write(
            "CREATE TEMP TABLE stage_rows (source_file_sha256 text, worksheet text, "
            "source_row_number integer, raw_cells jsonb) ON COMMIT DROP;\n"
        )
        stream.write("COPY stage_rows FROM STDIN WITH (FORMAT csv);\n")
        for worksheet in workbook.worksheets:
            rows = worksheet.iter_rows(values_only=True)
            header = next(rows)
            if list(header) != EXPECTED_HEADERS:
                raise RuntimeError("Workbook headers differ from the verified source")
            count = 0
            for row_number, row in enumerate(rows, start=2):
                if len(row) != len(EXPECTED_HEADERS):
                    raise RuntimeError("Workbook row width differs from the verified source")
                typed_cells = [fingerprint_value(value) for value in row]
                writer.writerow((
                    EXPECTED_SHA256, worksheet.title, row_number,
                    json.dumps(typed_cells, ensure_ascii=False, separators=(",", ":")),
                ))
                count += 1
                if count % 100_000 == 0:
                    print(f"{worksheet.title}: {count:,} source rows staged", flush=True)
            counts[worksheet.title] = count
            if count != EXPECTED_COUNTS[worksheet.title]:
                raise RuntimeError("Workbook row count differs from the verified source")
        stream.write("\\.\n")
        stream.write(FINALIZE_SQL.read_text(encoding="utf-8"))
        stream.write("\nCOMMIT;\n")
        stream.close()
        exit_code = process.wait(timeout=600)
        assert process.stdout is not None and process.stderr is not None
        output = process.stdout.read()
        process.stderr.read()  # Never echo SQL/COPY errors that may include source values.
        if exit_code:
            raise RuntimeError("PostgreSQL import failed; transaction rolled back (details withheld)")
        results = [line for line in output.splitlines() if line.startswith("IMPORT_RESULT|")]
        if len(results) != 1:
            raise RuntimeError("Import committed but no unambiguous aggregate result was returned")
        _, mode, inserted, seen, state = results[0].split("|")
        if state != "completed" or int(seen) != sum(EXPECTED_COUNTS.values()):
            raise RuntimeError("Import aggregate result did not reconcile")
        print(
            f"PASS: {mode}; rows_seen={seen}; rows_inserted_this_run={inserted}; "
            f"worksheets={counts}; elapsed_seconds={time.monotonic() - started:.1f}; "
            f"attempt_uuid={job_id}",
            flush=True,
        )
    except BaseException:
        if process.poll() is None:
            process.kill()
            process.wait()
        raise
    finally:
        workbook.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--idempotency-key", default="uci-502-full-v1")
    arguments = parser.parse_args()
    import_workbook(arguments.idempotency_key)
