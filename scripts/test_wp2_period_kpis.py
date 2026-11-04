"""Exercise period KPI SQL against the WP1 golden fixture; always roll back rows."""

from decimal import Decimal
from fractions import Fraction
import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = json.loads((ROOT / "tests/fixtures/kpi_policy_v1.json").read_text(encoding="utf-8"))
HASH = "F" * 64
SHEET = "WP1 synthetic fixture"
CONTAINER = "raa-g0-postgres-1"
DATABASE = "raa_wp2_validation"


def quoted(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


rows_json = json.dumps(FIXTURE["rows"], ensure_ascii=True)
if "$fixture$" in rows_json:
    raise SystemExit("Fixture contains SQL delimiter")

periods_sql = ",\n".join(
    f"({quoted(p['name'])}, {quoted(p['start_inclusive'])}::timestamp, "
    f"{quoted(p['end_exclusive'])}::timestamp)"
    for p in FIXTURE["periods"]
)

sql = f"""
BEGIN;
INSERT INTO retail.source_snapshots
    (source_file_sha256, dataset_id, source_filename, source_bytes,
     source_url, license_name, expected_data_rows)
VALUES ({quoted(HASH)}, 'wp1-synthetic', 'fixture.json', 1,
        'local://wp1-fixture', 'synthetic', {len(FIXTURE['rows'])});
INSERT INTO retail.source_sheets
    (source_file_sha256, worksheet, sheet_ordinal, original_headers,
     expected_data_rows)
VALUES ({quoted(HASH)}, {quoted(SHEET)}, 1,
        ('["Invoice","StockCode","Description","Quantity","InvoiceDate",' ||
         '"Price","CustomerID","Country"]')::jsonb, {len(FIXTURE['rows'])});
INSERT INTO retail.import_jobs
    (job_id, source_file_sha256, idempotency_key, state)
VALUES ('ffffffff-ffff-4fff-8fff-ffffffffffff', {quoted(HASH)},
        'wp1-period-test', 'completed');
CREATE TEMP TABLE fixture_rows ON COMMIT DROP AS
SELECT * FROM jsonb_to_recordset($fixture${rows_json}$fixture$::jsonb) AS r(
    source_row_number integer, invoice_no text, stock_code text,
    quantity numeric, unit_price_gbp numeric, customer_id text,
    invoice_datetime_raw timestamp, classification text);
INSERT INTO retail.source_rows
    (source_file_sha256, worksheet, source_row_number,
     first_import_job_id, raw_cells)
SELECT {quoted(HASH)}, {quoted(SHEET)}, f.source_row_number,
       'ffffffff-ffff-4fff-8fff-ffffffffffff',
       jsonb_build_array(
           jsonb_build_array('str', f.invoice_no),
           jsonb_build_array('str', f.stock_code),
           jsonb_build_array('null', ''),
           jsonb_build_array('numeric', f.quantity::text),
           jsonb_build_array('datetime', f.invoice_datetime_raw::text),
           jsonb_build_array('numeric', f.unit_price_gbp::text),
           jsonb_build_array(CASE WHEN f.customer_id IS NULL THEN 'null'
                                  ELSE 'str' END, coalesce(f.customer_id, '')),
           jsonb_build_array('str', 'Synthetic'))
FROM fixture_rows f;
INSERT INTO retail.invoice_lines
    (source_file_sha256, worksheet, source_row_number, policy_version,
     invoice_no, stock_code, quantity, invoice_datetime_raw,
     unit_price_gbp, customer_id, country, classification,
     signed_line_value_gbp)
SELECT {quoted(HASH)}, {quoted(SHEET)}, f.source_row_number, 'v1',
       f.invoice_no, f.stock_code, f.quantity, f.invoice_datetime_raw,
       f.unit_price_gbp, f.customer_id, 'Synthetic', f.classification,
       f.quantity * f.unit_price_gbp
FROM fixture_rows f;
SELECT 'KPI_RESULT|' || p.name || '|' || row_to_json(k)::text
FROM (VALUES {periods_sql}) AS p(name, start_inclusive, end_exclusive)
CROSS JOIN LATERAL retail.period_kpis_v1(
    {quoted(HASH)}, {quoted(SHEET)}, p.start_inclusive, p.end_exclusive) k;
DO $guard$
DECLARE rejected boolean := false;
BEGIN
    BEGIN
        PERFORM * FROM retail.period_kpis_v1(
            {quoted(HASH)}, {quoted(SHEET)}, '2010-12-01', '2010-12-01');
    EXCEPTION WHEN raise_exception THEN rejected := true;
    END;
    IF NOT rejected THEN RAISE EXCEPTION 'Empty period was accepted'; END IF;
    rejected := false;
    BEGIN
        PERFORM * FROM retail.period_kpis_v1(
            {quoted(HASH)}, 'wrong sheet', '2010-12-01', '2010-12-02');
    EXCEPTION WHEN raise_exception THEN rejected := true;
    END;
    IF NOT rejected THEN RAISE EXCEPTION 'Unknown sheet was accepted'; END IF;
END
$guard$;
DO $consistency$
DECLARE
    probe record;
    error_message text;
BEGIN
    FOR probe IN
        SELECT * FROM (VALUES
            (10, '11'::text, 'Synthetic'::text, true),
            (11, '10'::text, 'Other'::text, true),
            (12, '10'::text, 'Synthetic'::text, false)
        ) AS v(row_number, customer_id, country, expect_rejection)
    LOOP
        BEGIN
            INSERT INTO retail.source_rows
                (source_file_sha256, worksheet, source_row_number,
                 first_import_job_id, raw_cells)
            VALUES ({quoted(HASH)}, {quoted(SHEET)}, probe.row_number,
                    'ffffffff-ffff-4fff-8fff-ffffffffffff',
                    jsonb_build_array(0,0,0,0,0,0,0,0));
            INSERT INTO retail.invoice_lines
                (source_file_sha256, worksheet, source_row_number, policy_version,
                 invoice_no, stock_code, quantity, invoice_datetime_raw,
                 unit_price_gbp, customer_id, country, classification,
                 signed_line_value_gbp)
            VALUES ({quoted(HASH)}, {quoted(SHEET)}, probe.row_number, 'v1',
                    '100', 'X', 1, '2010-12-02 09:00:00', 1,
                    probe.customer_id, probe.country, 'sale', 1);
            PERFORM * FROM retail.period_kpis_v1(
                {quoted(HASH)}, {quoted(SHEET)}, '2010-12-01', '2010-12-02');
            IF probe.expect_rejection THEN
                RAISE EXCEPTION 'Expected consistency conflict was accepted';
            END IF;
            RAISE EXCEPTION 'Rollback successful consistency probe';
        EXCEPTION WHEN raise_exception THEN
            GET STACKED DIAGNOSTICS error_message = MESSAGE_TEXT;
            IF probe.expect_rejection
               AND error_message NOT LIKE 'Sale invoice consistency conflict:%' THEN
                RAISE;
            END IF;
            IF NOT probe.expect_rejection
               AND error_message <> 'Rollback successful consistency probe' THEN
                RAISE;
            END IF;
        END;
    END LOOP;
END
$consistency$;
ROLLBACK;
"""

result = subprocess.run(
    ["docker", "exec", "-i", CONTAINER, "psql", "-X", "-q", "-A", "-t",
     "-v", "ON_ERROR_STOP=1", "-U", "g0_user", "-d", DATABASE, "-f", "-"],
    input=sql, text=True, capture_output=True, check=False,
)
if result.returncode:
    print(result.stderr or result.stdout, file=sys.stderr)
    raise SystemExit(result.returncode)

observed = {}
for line in result.stdout.splitlines():
    if line.startswith("KPI_RESULT|"):
        _, name, payload = line.split("|", 2)
        observed[name] = json.loads(payload, parse_float=Decimal)

if len(observed) != len(FIXTURE["periods"]):
    raise SystemExit(f"Expected {len(FIXTURE['periods'])} periods, got {len(observed)}")

comparisons = 0
for period in FIXTURE["periods"]:
    name = period["name"]
    got = observed[name]
    for field, expected in period["expected"].items():
        actual = got[field]
        if expected is None:
            ok = actual is None
        elif field.endswith("_exact"):
            target = Fraction(expected)
            ok = actual is not None and abs(
                Fraction(Decimal(str(actual))) - target
            ) <= Fraction(1, 10**12)
        else:
            ok = actual is not None and Decimal(str(actual)) == Decimal(str(expected))
        if not ok:
            raise SystemExit(f"{name}.{field}: expected {expected}, got {actual}")
        comparisons += 1

if observed["first_day"]["period_source_rows"] != 7:
    raise SystemExit("First-day period row count differs")
if observed["first_day"]["missing_customer_sale_rows"] != 2:
    raise SystemExit("Missing-customer sales were not retained")
if observed["first_day"]["zero_price_sale_rows"] != 1:
    raise SystemExit("Zero-price accepted sale was not counted")
if observed["empty_day"]["customer_coverage_exact"] is not None:
    raise SystemExit("Empty-period coverage must be null")

print(f"PASS: {comparisons} golden KPI values across {len(observed)} periods; "
      "period, invoice-consistency and rollback guards passed")
