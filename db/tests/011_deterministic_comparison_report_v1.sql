-- Hand-checked positive/negative/zero baselines; no fixture persists.
BEGIN;
INSERT INTO retail.source_snapshots
    (source_file_sha256, dataset_id, source_filename, source_bytes,
     source_url, license_name, expected_data_rows)
VALUES (repeat('F',64), 'synthetic-comparison', 'comparison-fixture', 1,
        'local://comparison-fixture', 'synthetic', 10);
INSERT INTO retail.source_sheets
    (source_file_sha256, worksheet, sheet_ordinal, original_headers, expected_data_rows)
VALUES
    (repeat('F',64), 'Year 2009-2010', 1,
     '["Invoice","StockCode","Description","Quantity","InvoiceDate","Price","Customer ID","Country"]', 1),
    (repeat('F',64), 'Year 2010-2011', 2,
     '["Invoice","StockCode","Description","Quantity","InvoiceDate","Price","Customer ID","Country"]', 9);
INSERT INTO retail.import_jobs
    (job_id, source_file_sha256, idempotency_key, state)
VALUES ('ffffffff-ffff-4fff-8fff-ffffffffffff', repeat('F',64),
        'comparison-test', 'completed');
CREATE TEMP TABLE comparison_fixture_lines ON COMMIT DROP AS
SELECT * FROM (VALUES
    ('Year 2009-2010', 2, 'OVERLAP', 1, timestamp '2010-12-01 09:00', 1),
    ('Year 2010-2011', 2, 'OVERLAP', 1, timestamp '2010-12-01 09:00', 1),
    ('Year 2010-2011', 3, 'PRIOR', 2, timestamp '2011-01-07 09:00', 5),
    ('Year 2010-2011', 4, 'CPRIOR', -4, timestamp '2011-01-07 09:30', 5),
    ('Year 2010-2011', 5, 'SALECURRENT', 4, timestamp '2011-01-14 09:00', 5),
    ('Year 2010-2011', 6, 'CCURRENT', -1, timestamp '2011-01-14 09:30', 5),
    ('Year 2010-2011', 7, 'BOUNDARY', 100, timestamp '2011-01-14 10:00', 100),
    ('Year 2010-2011', 8, 'CZERO', -2, timestamp '2011-01-21 09:00', 5),
    ('Year 2010-2011', 9, 'AFTERZERO', 1, timestamp '2011-01-28 09:00', 7),
    ('Year 2010-2011', 10, 'BEFORE', 100, timestamp '2011-01-07 08:59:59', 100)
) AS v(worksheet, row_number, invoice_no, quantity, invoice_time, unit_price);
INSERT INTO retail.source_rows
    (source_file_sha256, worksheet, source_row_number, first_import_job_id, raw_cells)
SELECT repeat('F',64), worksheet, row_number,
       'ffffffff-ffff-4fff-8fff-ffffffffffff',
       jsonb_build_array(
           jsonb_build_array('str', invoice_no),
           jsonb_build_array('str', 'WIDGET'),
           jsonb_build_array('str', 'Widget'),
           jsonb_build_array('numeric', quantity::text),
           jsonb_build_array('datetime', invoice_time::text),
           jsonb_build_array('numeric', unit_price::text),
           jsonb_build_array('str', '10'), jsonb_build_array('str', 'UK'))
FROM comparison_fixture_lines;
SELECT * FROM retail.classify_snapshot_v1(repeat('F',64));

DO $golden$
DECLARE
    p jsonb;
    c jsonb;
    error_message text;
BEGIN
    p := retail.deterministic_comparison_report_v1(
        repeat('F',64), '2011-01-14 09:00', '2011-01-14 10:00', '2011-01-28 10:00');
    c := p->'changes';
    IF p->>'schema_version' IS DISTINCT FROM 'deterministic-comparison-report-v1'
       OR p->'prior_period'->>'period_start_inclusive'
            IS DISTINCT FROM '2011-01-07T09:00:00.000000'
       OR p->'prior_period'->>'period_end_exclusive'
            IS DISTINCT FROM '2011-01-07T10:00:00.000000'
       OR p->'prior_period'->>'source_as_of_exclusive'
            IS DISTINCT FROM p->'current_period'->>'source_as_of_exclusive'
       OR (p->'current_period'->'kpis'->>'period_source_rows')::int IS DISTINCT FROM 2
       OR (p->'prior_period'->'kpis'->>'period_source_rows')::int IS DISTINCT FROM 2
       OR (c->'sales_value_gbp'->>'current_value')::numeric IS DISTINCT FROM 20
       OR (c->'sales_value_gbp'->>'prior_value')::numeric IS DISTINCT FROM 10
       OR (c->'sales_value_gbp'->>'absolute_change')::numeric IS DISTINCT FROM 10
       OR (c->'sales_value_gbp'->>'relative_change')::numeric IS DISTINCT FROM 1
       OR c->'sales_value_gbp'->>'relative_change_status' IS DISTINCT FROM 'available'
       OR (c->'cancellation_magnitude_gbp'->>'relative_change')::numeric IS DISTINCT FROM -0.75
       OR (c->'net_recorded_sales_gbp'->>'prior_value')::numeric IS DISTINCT FROM -10
       OR (c->'net_recorded_sales_gbp'->>'absolute_change')::numeric IS DISTINCT FROM 25
       OR (c->'net_recorded_sales_gbp'->>'relative_change')::numeric IS DISTINCT FROM 2.5
       OR (c->'sales_invoice_count'->>'relative_change')::numeric IS DISTINCT FROM 0
       OR (c->'active_identified_customers'->>'relative_change')::numeric IS DISTINCT FROM 0
       OR (c->'units_sold'->>'relative_change')::numeric IS DISTINCT FROM 1
       OR (SELECT count(*) FROM jsonb_object_keys(c)) <> 6 THEN
        RAISE EXCEPTION 'Comparison golden values or seven-day boundaries differ';
    END IF;
    IF p IS DISTINCT FROM retail.deterministic_comparison_report_v1(
        repeat('F',64), '2011-01-14 09:00', '2011-01-14 10:00', '2011-01-28 10:00') THEN
        RAISE EXCEPTION 'Comparison payload is not repeatable';
    END IF;
    p := retail.deterministic_comparison_report_v1(
        repeat('F',64), '2011-01-28 09:00', '2011-01-28 10:00', '2011-01-28 10:00');
    c := p->'changes'->'sales_value_gbp';
    IF (c->>'absolute_change')::numeric IS DISTINCT FROM 7
       OR c->'relative_change' IS DISTINCT FROM 'null'::jsonb
       OR c->>'relative_change_status' IS DISTINCT FROM 'zero_baseline' THEN
        RAISE EXCEPTION 'Nonzero current with zero baseline differs';
    END IF;
    p := retail.deterministic_comparison_report_v1(
        repeat('F',64), '2011-02-04 09:00', '2011-02-04 10:00', '2011-02-04 10:00');
    IF (p->'changes'->'sales_value_gbp'->>'relative_change')::numeric IS DISTINCT FROM -1 THEN
        RAISE EXCEPTION 'Empty current with positive baseline differs';
    END IF;
    p := retail.deterministic_comparison_report_v1(
        repeat('F',64), '2011-02-11 09:00', '2011-02-11 10:00', '2011-02-11 10:00');
    IF EXISTS (SELECT 1 FROM jsonb_each(p->'changes') AS m
               WHERE (m.value->>'absolute_change')::numeric IS DISTINCT FROM 0
                  OR m.value->'relative_change' IS DISTINCT FROM 'null'::jsonb
                  OR m.value->>'relative_change_status' IS DISTINCT FROM 'zero_baseline') THEN
        RAISE EXCEPTION 'Two empty windows differ';
    END IF;
    BEGIN
        PERFORM retail.deterministic_comparison_report_v1(
            repeat('F',64), '2011-01-14 09:00', '2011-01-14 10:00', '2011-01-14 09:30');
        RAISE EXCEPTION 'Period beyond cutoff accepted';
    EXCEPTION WHEN raise_exception THEN
        GET STACKED DIAGNOSTICS error_message = MESSAGE_TEXT;
        IF error_message IS DISTINCT FROM
            'A snapshot, non-empty [start, end) period, and source as-of >= end are required' THEN
            RAISE;
        END IF;
    END;
END
$golden$;

-- Corrupt only PRIOR-period quality: the combined report must fail closed.
INSERT INTO retail.quality_findings
    (source_file_sha256, worksheet, source_row_number, policy_version,
     finding_code, severity, signed_line_value_gbp)
VALUES (repeat('F',64), 'Year 2010-2011', 3, 'v1',
        'missing_description', 'warning', 10);
DO $prior_quality$
DECLARE error_message text;
BEGIN
    BEGIN
        PERFORM retail.deterministic_comparison_report_v1(
            repeat('F',64), '2011-01-14 09:00', '2011-01-14 10:00', '2011-01-14 10:00');
        RAISE EXCEPTION 'Unexpected prior-period quality finding accepted';
    EXCEPTION WHEN raise_exception THEN
        GET STACKED DIAGNOSTICS error_message = MESSAGE_TEXT;
        IF error_message NOT LIKE 'Period quality findings differ from policy v1:%' THEN
            RAISE;
        END IF;
    END;
END
$prior_quality$;
SELECT 'PASS|comparison-golden|negative-baseline|zero-baseline|empty-current|empty-both|boundaries|repeatable|cutoff|prior-quality-gate';
ROLLBACK;
