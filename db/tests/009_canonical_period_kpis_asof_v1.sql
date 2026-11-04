-- Rollback-only source-time as-of test. No real source row is modified.
BEGIN;

INSERT INTO retail.source_snapshots
    (source_file_sha256, dataset_id, source_filename, source_bytes,
     source_url, license_name, expected_data_rows)
VALUES (repeat('C',64), 'synthetic-asof', 'asof-fixture', 1,
        'local://asof-fixture', 'synthetic', 4);
INSERT INTO retail.source_sheets
    (source_file_sha256, worksheet, sheet_ordinal, original_headers, expected_data_rows)
VALUES
    (repeat('C',64), 'Year 2009-2010', 1,
     jsonb_build_array('Invoice','StockCode','Description','Quantity',
                       'InvoiceDate','Price','Customer ID','Country'), 2),
    (repeat('C',64), 'Year 2010-2011', 2,
     jsonb_build_array('Invoice','StockCode','Description','Quantity',
                       'InvoiceDate','Price','Customer ID','Country'), 2);
INSERT INTO retail.import_jobs
    (job_id, source_file_sha256, idempotency_key, state)
VALUES ('cccccccc-cccc-4ccc-8ccc-cccccccccccc', repeat('C',64),
        'asof-test', 'completed');

CREATE TEMP TABLE asof_fixture_lines ON COMMIT DROP AS
SELECT * FROM (VALUES
    ('Year 2009-2010', 2, '099', 'PRE', timestamp '2010-11-30 23:00', 1::numeric, 1::numeric, '10'::text),
    ('Year 2009-2010', 3, '100', 'DUP', timestamp '2010-12-01 09:00', 1::numeric, 2::numeric, '10'::text),
    ('Year 2010-2011', 2, '100', 'DUP', timestamp '2010-12-01 09:00', 1::numeric, 2::numeric, '10'::text),
    ('Year 2010-2011', 3, '099', 'LATER', timestamp '2010-12-10 00:00', 1::numeric, 5::numeric, '20'::text)
) AS v(worksheet, row_number, invoice_no, stock_code, invoice_time,
       quantity, unit_price, customer_id);

INSERT INTO retail.source_rows
    (source_file_sha256, worksheet, source_row_number,
     first_import_job_id, raw_cells)
SELECT repeat('C',64), f.worksheet, f.row_number,
       'cccccccc-cccc-4ccc-8ccc-cccccccccccc',
       jsonb_build_array(
           jsonb_build_array('str', f.invoice_no),
           jsonb_build_array('str', f.stock_code),
           jsonb_build_array('null', ''),
           jsonb_build_array('numeric', f.quantity::text),
           jsonb_build_array('datetime', f.invoice_time::text),
           jsonb_build_array('numeric', f.unit_price::text),
           jsonb_build_array('str', f.customer_id),
           jsonb_build_array('str', 'UK'))
FROM asof_fixture_lines f;
INSERT INTO retail.invoice_lines
    (source_file_sha256, worksheet, source_row_number, policy_version,
     invoice_no, stock_code, quantity, invoice_datetime_raw,
     unit_price_gbp, customer_id, country, classification,
     signed_line_value_gbp)
SELECT repeat('C',64), f.worksheet, f.row_number, 'v1',
       f.invoice_no, f.stock_code, f.quantity, f.invoice_time,
       f.unit_price, f.customer_id, 'UK', 'sale',
       f.quantity * f.unit_price
FROM asof_fixture_lines f;

DO $test$
DECLARE
    k record;
    error_message text;
BEGIN
    -- The later row reuses the earlier invoice number across worksheets.
    -- The old global guard sees it, even for the earlier report window.
    BEGIN
        PERFORM * FROM retail.canonical_period_kpis_v1(
            repeat('C',64), '2010-11-30', '2010-12-01');
        RAISE EXCEPTION 'Global invoice guard did not see the later collision';
    EXCEPTION WHEN raise_exception THEN
        GET STACKED DIAGNOSTICS error_message = MESSAGE_TEXT;
        IF error_message NOT LIKE 'Canonical sale invoice conflict:%' THEN
            RAISE;
        END IF;
    END;

    SELECT * INTO k FROM retail.canonical_period_kpis_asof_v1(
        repeat('C',64), '2010-11-30', '2010-12-01', '2010-12-01');
    IF k.period_source_rows IS DISTINCT FROM 1
       OR k.sale_rows IS DISTINCT FROM 1
       OR k.sales_value_gbp IS DISTINCT FROM 1
       OR k.sales_invoice_count IS DISTINCT FROM 1
       OR k.active_identified_customers IS DISTINCT FROM 1 THEN
        RAISE EXCEPTION 'Later invoice entered the earlier as-of result';
    END IF;

    -- The exact later timestamp is still excluded by the exclusive cutoff.
    SELECT * INTO k FROM retail.canonical_period_kpis_asof_v1(
        repeat('C',64), '2010-11-30', '2010-12-01', '2010-12-10');
    IF k.period_source_rows IS DISTINCT FROM 1
       OR k.sales_value_gbp IS DISTINCT FROM 1 THEN
        RAISE EXCEPTION 'Exclusive as-of boundary included the later invoice';
    END IF;

    -- Once the cutoff includes the later row, its invoice conflict is visible.
    BEGIN
        PERFORM * FROM retail.canonical_period_kpis_asof_v1(
            repeat('C',64), '2010-11-30', '2010-12-01', '2010-12-11');
        RAISE EXCEPTION 'As-of invoice conflict was accepted';
    EXCEPTION WHEN raise_exception THEN
        GET STACKED DIAGNOSTICS error_message = MESSAGE_TEXT;
        IF error_message NOT LIKE 'Canonical as-of sale invoice conflict:%' THEN
            RAISE;
        END IF;
    END;

    BEGIN
        PERFORM * FROM retail.canonical_period_kpis_asof_v1(
            repeat('C',64), '2010-11-30', '2010-12-02', '2010-12-01');
        RAISE EXCEPTION 'Report period beyond as-of cutoff was accepted';
    EXCEPTION WHEN raise_exception THEN
        GET STACKED DIAGNOSTICS error_message = MESSAGE_TEXT;
        IF error_message NOT LIKE 'A snapshot, non-empty %' THEN
            RAISE;
        END IF;
    END;
END
$test$;

SELECT 'PASS|asof-earlier-window|exclusive-boundary|later-invoice-guard|invalid-cutoff';
ROLLBACK;
