-- Hand-checked, rollback-only cross-cutover KPI and invoice-ambiguity test.
BEGIN;

INSERT INTO retail.source_snapshots
    (source_file_sha256, dataset_id, source_filename, source_bytes,
     source_url, license_name, expected_data_rows)
VALUES (repeat('A',64), 'synthetic-merged-kpi', 'merged-fixture', 1,
        'local://merged-fixture', 'synthetic', 14);
INSERT INTO retail.source_sheets
    (source_file_sha256, worksheet, sheet_ordinal, original_headers, expected_data_rows)
VALUES
    (repeat('A',64), 'Year 2009-2010', 1,
     jsonb_build_array('Invoice','StockCode','Description','Quantity',
                       'InvoiceDate','Price','Customer ID','Country'), 7),
    (repeat('A',64), 'Year 2010-2011', 2,
     jsonb_build_array('Invoice','StockCode','Description','Quantity',
                       'InvoiceDate','Price','Customer ID','Country'), 7);
INSERT INTO retail.import_jobs
    (job_id, source_file_sha256, idempotency_key, state)
VALUES ('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', repeat('A',64),
        'merged-kpi-test', 'completed');

CREATE TEMP TABLE fixture_lines ON COMMIT DROP AS
SELECT * FROM (VALUES
    ('Year 2009-2010', 2, '099', 'PRE', timestamp '2010-11-30 23:00', 1::numeric, 1::numeric, '10'::text, 'sale'),
    ('Year 2009-2010', 3, '100', 'DUP', timestamp '2010-12-01 09:00', 2::numeric, 2::numeric, '10'::text, 'sale'),
    ('Year 2009-2010', 4, '100', 'DUP', timestamp '2010-12-01 09:00', 2::numeric, 2::numeric, '10'::text, 'sale'),
    ('Year 2009-2010', 5, 'C101', 'CAN', timestamp '2010-12-02 10:00', -1::numeric, 2::numeric, '10'::text, 'cancellation'),
    ('Year 2009-2010', 6, '103', 'ADJ', timestamp '2010-12-02 11:00', -1::numeric, 3::numeric, '10'::text, 'other_adjustment'),
    ('Year 2009-2010', 7, '104', 'BAD', timestamp '2010-12-02 12:00', 1::numeric, -4::numeric, '10'::text, 'invalid'),
    ('Year 2009-2010', 8, '105', 'ZERO', timestamp '2010-12-02 13:00', 0::numeric, 1::numeric, '10'::text, 'zero_quantity_non_sales'),
    ('Year 2010-2011', 2, '100', 'DUP', timestamp '2010-12-01 09:00', 2::numeric, 2::numeric, '10'::text, 'sale'),
    ('Year 2010-2011', 3, '100', 'DUP', timestamp '2010-12-01 09:00', 2::numeric, 2::numeric, '10'::text, 'sale'),
    ('Year 2010-2011', 4, 'C101', 'CAN', timestamp '2010-12-02 10:00', -1::numeric, 2::numeric, '10'::text, 'cancellation'),
    ('Year 2010-2011', 5, '102', 'POST', timestamp '2010-12-10 00:00', 1::numeric, 5::numeric, NULL::text, 'sale'),
    ('Year 2010-2011', 6, '103', 'ADJ', timestamp '2010-12-02 11:00', -1::numeric, 3::numeric, '10'::text, 'other_adjustment'),
    ('Year 2010-2011', 7, '104', 'BAD', timestamp '2010-12-02 12:00', 1::numeric, -4::numeric, '10'::text, 'invalid'),
    ('Year 2010-2011', 8, '105', 'ZERO', timestamp '2010-12-02 13:00', 0::numeric, 1::numeric, '10'::text, 'zero_quantity_non_sales')
) AS v(worksheet, row_number, invoice_no, stock_code, invoice_time,
       quantity, unit_price, customer_id, class);

INSERT INTO retail.source_rows
    (source_file_sha256, worksheet, source_row_number,
     first_import_job_id, raw_cells)
SELECT repeat('A',64), f.worksheet, f.row_number,
       'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
       jsonb_build_array(
           jsonb_build_array('str', f.invoice_no),
           jsonb_build_array('str', f.stock_code),
           jsonb_build_array('null', ''),
           jsonb_build_array('numeric', f.quantity::text),
           jsonb_build_array('datetime', f.invoice_time::text),
           jsonb_build_array('numeric', f.unit_price::text),
           jsonb_build_array(CASE WHEN f.customer_id IS NULL THEN 'null'
                                  ELSE 'str' END, coalesce(f.customer_id,'')),
           jsonb_build_array('str', 'UK'))
FROM fixture_lines f;
INSERT INTO retail.invoice_lines
    (source_file_sha256, worksheet, source_row_number, policy_version,
     invoice_no, stock_code, quantity, invoice_datetime_raw,
     unit_price_gbp, customer_id, country, classification,
     signed_line_value_gbp)
SELECT repeat('A',64), f.worksheet, f.row_number, 'v1',
       f.invoice_no, f.stock_code, f.quantity, f.invoice_time,
       f.unit_price, f.customer_id, 'UK', f.class,
       f.quantity * f.unit_price
FROM fixture_lines f;

DO $golden$
DECLARE
    k record;
BEGIN
    SELECT * INTO k FROM retail.canonical_period_kpis_v1(
        repeat('A',64), '2010-11-30', '2010-12-11');
    IF k.period_source_rows IS DISTINCT FROM 8
       OR k.sale_rows IS DISTINCT FROM 4
       OR k.cancellation_rows IS DISTINCT FROM 1
       OR k.other_adjustment_rows IS DISTINCT FROM 1
       OR k.invalid_rows IS DISTINCT FROM 1
       OR k.zero_quantity_rows IS DISTINCT FROM 1
       OR k.other_adjustment_signed_gbp IS DISTINCT FROM -3
       OR k.invalid_signed_gbp IS DISTINCT FROM -4
       OR k.invalid_value_calculable_rows IS DISTINCT FROM 1
       OR k.sales_value_gbp IS DISTINCT FROM 14
       OR k.cancellation_magnitude_gbp IS DISTINCT FROM 2
       OR k.net_recorded_sales_gbp IS DISTINCT FROM 12
       OR k.sales_invoice_count IS DISTINCT FROM 3
       OR k.average_sales_invoice_value_exact IS NULL
       OR abs(k.average_sales_invoice_value_exact * 3 - 14) > 0.000000000001
       OR k.active_identified_customers IS DISTINCT FROM 1
       OR k.missing_customer_sale_rows IS DISTINCT FROM 1
       OR k.customer_coverage_exact IS DISTINCT FROM 0.75
       OR k.units_sold IS DISTINCT FROM 6
       OR k.cancellation_to_sales_value_ratio_exact IS NULL
       OR abs(k.cancellation_to_sales_value_ratio_exact * 7 - 1)
            > 0.000000000001 THEN
        RAISE EXCEPTION 'Merged cross-cutover KPI golden values differ';
    END IF;
    SELECT * INTO k FROM retail.canonical_period_kpis_v1(
        repeat('A',64), '2010-12-01', '2010-12-02');
    IF k.period_source_rows IS DISTINCT FROM 2
       OR k.sales_value_gbp IS DISTINCT FROM 8
       OR k.sales_invoice_count IS DISTINCT FROM 1
       OR k.average_sales_invoice_value_exact IS DISTINCT FROM 8 THEN
        RAISE EXCEPTION 'Overlapping rows were doubled or collapsed';
    END IF;
    SELECT * INTO k FROM retail.canonical_period_kpis_v1(
        repeat('A',64), '2010-12-02', '2010-12-03');
    IF k.sale_rows IS DISTINCT FROM 0
       OR k.cancellation_rows IS DISTINCT FROM 1
       OR k.other_adjustment_rows IS DISTINCT FROM 1
       OR k.invalid_rows IS DISTINCT FROM 1
       OR k.zero_quantity_rows IS DISTINCT FROM 1
       OR k.sales_value_gbp IS DISTINCT FROM 0
       OR k.cancellation_magnitude_gbp IS DISTINCT FROM 2
       OR k.average_sales_invoice_value_exact IS NOT NULL
       OR k.cancellation_to_sales_value_ratio_exact IS NOT NULL THEN
        RAISE EXCEPTION 'Cancellation-only zero-denominator case differs';
    END IF;
    SELECT * INTO k FROM retail.canonical_period_kpis_v1(
        repeat('A',64), '2010-12-03', '2010-12-04');
    IF k.period_source_rows IS DISTINCT FROM 0
       OR k.sales_value_gbp IS DISTINCT FROM 0
       OR k.sales_invoice_count IS DISTINCT FROM 0
       OR k.average_sales_invoice_value_exact IS NOT NULL THEN
        RAISE EXCEPTION 'Empty canonical period differs';
    END IF;
END
$golden$;

-- A pre-cutover sale reuses a post-cutover invoice number. The overlap still
-- matches exactly, but canonical invoice identity is ambiguous and must fail.
INSERT INTO retail.source_snapshots
    (source_file_sha256, dataset_id, source_filename, source_bytes,
     source_url, license_name, expected_data_rows)
SELECT repeat('B',64), dataset_id, source_filename, source_bytes,
       source_url, license_name, expected_data_rows
FROM retail.source_snapshots WHERE source_file_sha256 = repeat('A',64);
INSERT INTO retail.source_sheets
    (source_file_sha256, worksheet, sheet_ordinal, original_headers, expected_data_rows)
SELECT repeat('B',64), worksheet, sheet_ordinal, original_headers,
       expected_data_rows
FROM retail.source_sheets WHERE source_file_sha256 = repeat('A',64);
INSERT INTO retail.import_jobs
    (job_id, source_file_sha256, idempotency_key, state)
VALUES ('bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb', repeat('B',64),
        'merged-kpi-collision-test', 'completed');
INSERT INTO retail.source_rows
    (source_file_sha256, worksheet, source_row_number,
     first_import_job_id, raw_cells)
SELECT repeat('B',64), worksheet, source_row_number,
       'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
       CASE WHEN worksheet = 'Year 2009-2010' AND source_row_number = 2
            THEN jsonb_set(raw_cells, '{0,1}', '"100"'::jsonb)
            ELSE raw_cells END
FROM retail.source_rows WHERE source_file_sha256 = repeat('A',64);
INSERT INTO retail.invoice_lines
    (source_file_sha256, worksheet, source_row_number, policy_version,
     invoice_no, stock_code, description, quantity, invoice_datetime_raw,
     unit_price_gbp, customer_id, country, classification,
     signed_line_value_gbp)
SELECT repeat('B',64), worksheet, source_row_number, policy_version,
       CASE WHEN worksheet = 'Year 2009-2010' AND source_row_number = 2
            THEN '100' ELSE invoice_no END,
       stock_code, description, quantity, invoice_datetime_raw,
       unit_price_gbp, customer_id, country, classification,
       signed_line_value_gbp
FROM retail.invoice_lines WHERE source_file_sha256 = repeat('A',64);

DO $negative$
DECLARE error_message text;
BEGIN
    BEGIN
        PERFORM * FROM retail.canonical_period_kpis_v1(
            repeat('B',64), '2010-12-01', '2010-12-02');
        RAISE EXCEPTION 'Cross-sheet invoice collision was accepted';
    EXCEPTION WHEN raise_exception THEN
        GET STACKED DIAGNOSTICS error_message = MESSAGE_TEXT;
        IF error_message NOT LIKE 'Canonical sale invoice conflict:%' THEN
            RAISE;
        END IF;
    END;
END
$negative$;

SELECT 'PASS|merged-kpi-golden|cross-cutover-invoice-guard';
ROLLBACK;
