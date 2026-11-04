-- Rollback-only deterministic report test with quality and empty windows.
BEGIN;

INSERT INTO retail.source_snapshots
    (source_file_sha256, dataset_id, source_filename, source_bytes,
     source_url, license_name, expected_data_rows)
VALUES (repeat('D',64), 'synthetic-report', 'report-fixture', 1,
        'local://report-fixture', 'synthetic', 4);
INSERT INTO retail.source_sheets
    (source_file_sha256, worksheet, sheet_ordinal, original_headers, expected_data_rows)
VALUES
    (repeat('D',64), 'Year 2009-2010', 1,
     jsonb_build_array('Invoice','StockCode','Description','Quantity',
                       'InvoiceDate','Price','Customer ID','Country'), 2),
    (repeat('D',64), 'Year 2010-2011', 2,
     jsonb_build_array('Invoice','StockCode','Description','Quantity',
                       'InvoiceDate','Price','Customer ID','Country'), 2);
INSERT INTO retail.import_jobs
    (job_id, source_file_sha256, idempotency_key, state)
VALUES ('dddddddd-dddd-4ddd-8ddd-dddddddddddd', repeat('D',64),
        'report-test', 'completed');

CREATE TEMP TABLE report_fixture_lines ON COMMIT DROP AS
SELECT * FROM (VALUES
    ('Year 2009-2010', 2, '099', 'PRE', NULL::text,
     1::numeric, timestamp '2010-11-30 23:00', 2::numeric, NULL::text),
    ('Year 2009-2010', 3, '100', 'DUP', 'Widget'::text,
     1::numeric, timestamp '2010-12-01 09:00', 3::numeric, '10'::text),
    ('Year 2010-2011', 2, '100', 'DUP', 'Widget'::text,
     1::numeric, timestamp '2010-12-01 09:00', 3::numeric, '10'::text),
    ('Year 2010-2011', 3, '101', 'LATER', NULL::text,
     1::numeric, timestamp '2010-12-10 01:00', 0::numeric, '11'::text)
) AS v(worksheet, row_number, invoice_no, stock_code, description,
       quantity, invoice_time, unit_price, customer_id);

INSERT INTO retail.source_rows
    (source_file_sha256, worksheet, source_row_number,
     first_import_job_id, raw_cells)
SELECT repeat('D',64), f.worksheet, f.row_number,
       'dddddddd-dddd-4ddd-8ddd-dddddddddddd',
       jsonb_build_array(
           jsonb_build_array('str', f.invoice_no),
           jsonb_build_array('str', f.stock_code),
           jsonb_build_array(CASE WHEN f.description IS NULL THEN 'null'
                                  ELSE 'str' END, coalesce(f.description,'')),
           jsonb_build_array('numeric', f.quantity::text),
           jsonb_build_array('datetime', f.invoice_time::text),
           jsonb_build_array('numeric', f.unit_price::text),
           jsonb_build_array(CASE WHEN f.customer_id IS NULL THEN 'null'
                                  ELSE 'str' END, coalesce(f.customer_id,'')),
           jsonb_build_array('str', 'UK'))
FROM report_fixture_lines f;
SELECT * FROM retail.classify_snapshot_v1(repeat('D',64));

DO $golden$
DECLARE
    p jsonb;
    code_count bigint;
BEGIN
    p := retail.deterministic_period_report_v1(
        repeat('D',64), '2010-11-30', '2010-12-01', '2010-12-01');
    IF p->>'schema_version' IS DISTINCT FROM 'deterministic-period-report-v1'
       OR p->>'source_file_sha256' IS DISTINCT FROM repeat('D',64)
       OR p->>'source_as_of_exclusive' IS DISTINCT FROM '2010-12-01T00:00:00.000000'
       OR (p->'kpis'->>'period_source_rows')::bigint IS DISTINCT FROM 1
       OR (p->'kpis'->>'sale_rows')::bigint IS DISTINCT FROM 1
       OR (p->'kpis'->>'sales_value_gbp')::numeric IS DISTINCT FROM 2
       OR (p->'kpis'->>'missing_customer_sale_rows')::bigint IS DISTINCT FROM 1
       OR (p->'quality'->>'flagged_source_rows')::bigint IS DISTINCT FROM 1
       OR (p->'quality'->>'finding_rows')::bigint IS DISTINCT FROM 2
       OR (p->'quality'->'finding_rows_by_code'->>'missing_customer_id')::bigint
            IS DISTINCT FROM 1
       OR (p->'quality'->'finding_rows_by_code'->>'missing_description')::bigint
            IS DISTINCT FROM 1
       OR (p->'quality'->'finding_rows_by_code'->>'zero_price_sale')::bigint
            IS DISTINCT FROM 0 THEN
        RAISE EXCEPTION 'Golden earlier report differs';
    END IF;
    IF p IS DISTINCT FROM retail.deterministic_period_report_v1(
        repeat('D',64), '2010-11-30', '2010-12-01', '2010-12-01') THEN
        RAISE EXCEPTION 'Identical report inputs did not reproduce JSONB output';
    END IF;

    p := retail.deterministic_period_report_v1(
        repeat('D',64), '2011-01-01 00:00', '2011-01-01 01:00',
        '2011-01-01 01:00');
    SELECT count(*) INTO code_count
    FROM jsonb_object_keys(p->'quality'->'finding_rows_by_code');
    IF (p->'kpis'->>'period_source_rows')::bigint IS DISTINCT FROM 0
       OR (p->'kpis'->>'sales_value_gbp')::numeric IS DISTINCT FROM 0
       OR p->'kpis'->'average_sales_invoice_value_exact' IS DISTINCT FROM 'null'::jsonb
       OR (p->'quality'->>'flagged_source_rows')::bigint IS DISTINCT FROM 0
       OR (p->'quality'->>'finding_rows')::bigint IS DISTINCT FROM 0
       OR code_count IS DISTINCT FROM 12 THEN
        RAISE EXCEPTION 'Empty report differs';
    END IF;

    p := retail.deterministic_period_report_v1(
        repeat('D',64), '2010-12-10', '2010-12-11', '2010-12-11');
    IF (p->'kpis'->>'period_source_rows')::bigint IS DISTINCT FROM 1
       OR (p->'kpis'->>'zero_price_sale_rows')::bigint IS DISTINCT FROM 1
       OR (p->'quality'->>'flagged_source_rows')::bigint IS DISTINCT FROM 1
       OR (p->'quality'->>'finding_rows')::bigint IS DISTINCT FROM 2
       OR (p->'quality'->'finding_rows_by_code'->>'zero_price_sale')::bigint
            IS DISTINCT FROM 1 THEN
        RAISE EXCEPTION 'Zero-price quality report differs';
    END IF;
END
$golden$;

-- A complete normalized fixture with omitted quality findings must fail
-- closed instead of displaying an apparently healthy zero.
INSERT INTO retail.source_snapshots
    (source_file_sha256, dataset_id, source_filename, source_bytes,
     source_url, license_name, expected_data_rows)
SELECT repeat('E',64), dataset_id, source_filename, source_bytes,
       source_url, license_name, expected_data_rows
FROM retail.source_snapshots WHERE source_file_sha256 = repeat('D',64);
INSERT INTO retail.source_sheets
    (source_file_sha256, worksheet, sheet_ordinal, original_headers, expected_data_rows)
SELECT repeat('E',64), worksheet, sheet_ordinal, original_headers,
       expected_data_rows
FROM retail.source_sheets WHERE source_file_sha256 = repeat('D',64);
INSERT INTO retail.import_jobs
    (job_id, source_file_sha256, idempotency_key, state)
VALUES ('eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee', repeat('E',64),
        'missing-quality-test', 'completed');
INSERT INTO retail.source_rows
    (source_file_sha256, worksheet, source_row_number,
     first_import_job_id, raw_cells)
SELECT repeat('E',64), worksheet, source_row_number,
       'eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee', raw_cells
FROM retail.source_rows WHERE source_file_sha256 = repeat('D',64);
INSERT INTO retail.invoice_lines
    (source_file_sha256, worksheet, source_row_number, policy_version,
     invoice_no, stock_code, description, quantity, invoice_datetime_raw,
     unit_price_gbp, customer_id, country, classification,
     signed_line_value_gbp)
SELECT repeat('E',64), worksheet, source_row_number, policy_version,
       invoice_no, stock_code, description, quantity, invoice_datetime_raw,
       unit_price_gbp, customer_id, country, classification,
       signed_line_value_gbp
FROM retail.invoice_lines WHERE source_file_sha256 = repeat('D',64);

DO $negative$
DECLARE error_message text;
BEGIN
    BEGIN
        PERFORM retail.deterministic_period_report_v1(
            repeat('E',64), '2010-11-30', '2010-12-01', '2010-12-01');
        RAISE EXCEPTION 'Missing quality findings were accepted';
    EXCEPTION WHEN raise_exception THEN
        GET STACKED DIAGNOSTICS error_message = MESSAGE_TEXT;
        IF error_message NOT LIKE 'Period quality findings differ from policy v1:%' THEN
            RAISE;
        END IF;
    END;
END
$negative$;

SELECT 'PASS|report-golden|repeatable|empty-window|zero-price|missing-quality-gate';
ROLLBACK;
