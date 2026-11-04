"""One-off G0 capacity test: stream every source row to an isolated SQL table.

This is not the product importer. The workbook is opened read-only, each physical
source row keeps its worksheet and row number, and no source rows are deduplicated.
Only aggregate counts and timings are printed; raw values stay in the ignored DB.
"""

from __future__ import annotations

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
EXPECTED_SHA256 = "BCBE73B35F5B7BABF197FB0CB983A11F5D9FF929078D4AA53D171B1F2DF2E980"
EXPECTED_COUNTS = {"Year 2009-2010": 525_461, "Year 2010-2011": 541_910}
CONTAINER = "raa-g0-postgres-1"


def docker_psql(sql: str) -> str:
    result = subprocess.run(
        ["docker", "exec", CONTAINER, "psql", "-X", "-A", "-t", "-v", "ON_ERROR_STOP=1", "-U", "g0_user", "-d", "n8n", "-c", sql],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        raise RuntimeError("PostgreSQL verification failed; details withheld to protect source data")
    return result.stdout.strip()


def main() -> None:
    digest = hashlib.sha256()
    with WORKBOOK.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    if digest.hexdigest().upper() != EXPECTED_SHA256:
        raise RuntimeError("Source workbook hash mismatch; import not started")

    run_id = str(uuid4())
    workbook = openpyxl.load_workbook(WORKBOOK, read_only=True, data_only=True)
    if set(workbook.sheetnames) != set(EXPECTED_COUNTS):
        raise RuntimeError("Unexpected worksheets; import not started")

    command = [
        "docker", "exec", "-i", CONTAINER, "psql", "-X", "-q", "-v", "ON_ERROR_STOP=1", "-U", "g0_user", "-d", "n8n"
    ]
    process = subprocess.Popen(
        command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        text=True, encoding="utf-8",
    )
    assert process.stdin is not None
    start = time.monotonic()
    counts: dict[str, int] = {}
    try:
        process.stdin.write("BEGIN;\n")
        process.stdin.write("CREATE SCHEMA IF NOT EXISTS g0_stress;\n")
        process.stdin.write(
            "CREATE TABLE IF NOT EXISTS g0_stress.raw_rows ("
            "run_id uuid NOT NULL, worksheet text NOT NULL, row_no integer NOT NULL, "
            "payload jsonb NOT NULL, PRIMARY KEY (run_id, worksheet, row_no));\n"
        )
        process.stdin.write(
            "COPY g0_stress.raw_rows (run_id, worksheet, row_no, payload) "
            "FROM STDIN WITH (FORMAT csv);\n"
        )
        writer = csv.writer(process.stdin, lineterminator="\n")
        for worksheet in workbook.worksheets:
            count = 0
            for row_no, values in enumerate(worksheet.iter_rows(values_only=True), start=1):
                if row_no == 1:
                    continue
                payload = json.dumps(
                    [fingerprint_value(value) for value in values],
                    ensure_ascii=False, separators=(",", ":"),
                )
                writer.writerow((run_id, worksheet.title, row_no, payload))
                count += 1
                if count % 100_000 == 0:
                    print(f"{worksheet.title}: {count:,} rows streamed", flush=True)
            counts[worksheet.title] = count
            if count != EXPECTED_COUNTS[worksheet.title]:
                raise RuntimeError("Worksheet row count mismatch; transaction will roll back")
        process.stdin.write("\\.\nCOMMIT;\n")
        process.stdin.close()
        if process.wait(timeout=120) != 0:
            raise RuntimeError("PostgreSQL COPY failed; details withheld to protect source data")
    except BaseException:
        if process.poll() is None:
            process.kill()
            process.wait()
        raise
    finally:
        workbook.close()

    elapsed = time.monotonic() - start
    summary = docker_psql(
        "SELECT worksheet, count(*), min(row_no), max(row_no) "
        "FROM g0_stress.raw_rows WHERE run_id = '" + run_id + "' "
        "GROUP BY worksheet ORDER BY worksheet"
    )
    total = int(docker_psql(
        "SELECT count(*) FROM g0_stress.raw_rows WHERE run_id = '" + run_id + "'"
    ))
    relation_bytes = int(docker_psql(
        "SELECT pg_total_relation_size('g0_stress.raw_rows')"
    ))
    if total != sum(EXPECTED_COUNTS.values()):
        raise RuntimeError("Database total differs from source profile")
    print(f"PASS: run_id={run_id}; imported_rows={total:,}; elapsed={elapsed:.1f}s", flush=True)
    print(f"SQL worksheet counts and source row ranges: {summary}", flush=True)
    print(f"Total stress table plus index bytes: {relation_bytes:,}", flush=True)


if __name__ == "__main__":
    main()
