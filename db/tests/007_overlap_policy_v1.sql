-- Synthetic, rollback-only test of migration 006. No real source is changed.
BEGIN;

INSERT INTO retail.source_snapshots
    (source_file_sha256, dataset_id, source_filename, source_bytes,
     source_url, license_name, expected_data_rows)
VALUES (repeat('E',64), 'synthetic-overlap', 'overlap-fixture', 1,
        'local://overlap-fixture', 'synthetic', 8);
INSERT INTO retail.source_sheets
    (source_file_sha256, worksheet, sheet_ordinal, original_headers, expected_data_rows)
VALUES
    (repeat('E',64), 'Year 2009-2010', 1,
     jsonb_build_array('Invoice','StockCode','Description','Quantity',
                       'InvoiceDate','Price','Customer ID','Country'), 4),
    (repeat('E',64), 'Year 2010-2011', 2,
     jsonb_build_array('Invoice','StockCode','Description','Quantity',
                       'InvoiceDate','Price','Customer ID','Country'), 4);
INSERT INTO retail.import_jobs
    (job_id, source_file_sha256, idempotency_key, state)
VALUES ('eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee', repeat('E',64),
        'overlap-test', 'completed');

CREATE TEMP TABLE fixture_lines ON COMMIT DROP AS
SELECT * FROM (VALUES
    ('Year 2009-2010', 2, '099', 'PRE', timestamp '2010-11-30 23:00', 1::numeric, 1::numeric, 'sale'),
    ('Year 2009-2010', 3, '100', 'DUP', timestamp '2010-12-01 09:00', 1::numeric, 2::numeric, 'sale'),
    ('Year 2009-2010', 4, '100', 'DUP', timestamp '2010-12-01 09:00', 1::numeric, 2::numeric, 'sale'),
    ('Year 2009-2010', 5, 'C101', 'CAN', timestamp '2010-12-02 10:00', -1::numeric, 3::numeric, 'cancellation'),
    ('Year 2010-2011', 2, '100', 'DUP', timestamp '2010-12-01 09:00', 1::numeric, 2::numeric, 'sale'),
    ('Year 2010-2011', 3, '100', 'DUP', timestamp '2010-12-01 09:00', 1::numeric, 2::numeric, 'sale'),
    ('Year 2010-2011', 4, 'C101', 'CAN', timestamp '2010-12-02 10:00', -1::numeric, 3::numeric, 'cancellation'),
    ('Year 2010-2011', 5, '102', 'POST', timestamp '2010-12-10 00:00', 1::numeric, 4::numeric, 'sale')
) AS v(worksheet, row_number, invoice_no, stock_code, invoice_time,
       quantity, unit_price, class);

INSERT INTO retail.source_rows
    (source_file_sha256, worksheet, source_row_number,
     first_import_job_id, raw_cells)
SELECT repeat('E',64), f.worksheet, f.row_number,
       'eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee',
       jsonb_build_array(
           jsonb_build_array('str', f.invoice_no),
           jsonb_build_array('str', f.stock_code),
           jsonb_build_array('null', ''),
           jsonb_build_array('numeric', f.quantity::text),
           jsonb_build_array('datetime', f.invoice_time::text),
           jsonb_build_array('numeric', f.unit_price::text),
           jsonb_build_array('str', '10'),
           jsonb_build_array('str', 'UK'))
FROM fixture_lines f;
INSERT INTO retail.invoice_lines
    (source_file_sha256, worksheet, source_row_number, policy_version,
     invoice_no, stock_code, quantity, invoice_datetime_raw,
     unit_price_gbp, customer_id, country, classification,
     signed_line_value_gbp)
SELECT repeat('E',64), f.worksheet, f.row_number, 'v1',
       f.invoice_no, f.stock_code, f.quantity, f.invoice_time,
       f.unit_price, '10', 'UK', f.class, f.quantity * f.unit_price
FROM fixture_lines f;

DO $test$
DECLARE selected_count bigint;
        older_count bigint;
        newer_count bigint;
        duplicate_count bigint;
BEGIN
    PERFORM retail.assert_uci_502_overlap_v1(repeat('E',64));
    SELECT count(*),
           count(*) FILTER (WHERE worksheet = 'Year 2009-2010'),
           count(*) FILTER (WHERE worksheet = 'Year 2010-2011')
    INTO selected_count, older_count, newer_count
    FROM retail.canonical_period_line_keys_v1(
        repeat('E',64), '2010-11-30', '2010-12-11');
    IF selected_count <> 5 OR older_count <> 1 OR newer_count <> 4 THEN
        RAISE EXCEPTION 'Canonical cutover selected wrong source rows';
    END IF;
    SELECT count(*) INTO duplicate_count
    FROM retail.canonical_period_line_keys_v1(
        repeat('E',64), '2010-12-01', '2010-12-02') k
    JOIN retail.invoice_lines l USING
        (source_file_sha256, worksheet, source_row_number, policy_version)
    WHERE l.stock_code = 'DUP';
    IF duplicate_count <> 2 THEN
        RAISE EXCEPTION 'Equal-valued rows within the selected sheet were lost';
    END IF;
    IF (SELECT count(*) FROM retail.canonical_period_line_keys_v1(
            repeat('E',64), '2010-11-30', '2010-12-01')) <> 1
       OR (SELECT count(*) FROM retail.canonical_period_line_keys_v1(
            repeat('E',64), '2010-12-10', '2010-12-11')) <> 1 THEN
        RAISE EXCEPTION 'Cutover or exclusive end boundary is wrong';
    END IF;
END
$test$;

-- Same counts and line classifications, but one source value differs.
INSERT INTO retail.source_snapshots
    (source_file_sha256, dataset_id, source_filename, source_bytes,
     source_url, license_name, expected_data_rows)
SELECT repeat('D',64), dataset_id, source_filename, source_bytes,
       source_url, license_name, expected_data_rows
FROM retail.source_snapshots WHERE source_file_sha256 = repeat('E',64);
INSERT INTO retail.source_sheets
    (source_file_sha256, worksheet, sheet_ordinal, original_headers, expected_data_rows)
SELECT repeat('D',64), worksheet, sheet_ordinal, original_headers,
       expected_data_rows
FROM retail.source_sheets WHERE source_file_sha256 = repeat('E',64);
INSERT INTO retail.import_jobs
    (job_id, source_file_sha256, idempotency_key, state)
VALUES ('dddddddd-dddd-4ddd-8ddd-dddddddddddd', repeat('D',64),
        'overlap-mismatch-test', 'completed');
INSERT INTO retail.source_rows
    (source_file_sha256, worksheet, source_row_number,
     first_import_job_id, raw_cells)
SELECT repeat('D',64), worksheet, source_row_number,
       'dddddddd-dddd-4ddd-8ddd-dddddddddddd',
       CASE WHEN worksheet = 'Year 2010-2011' AND source_row_number = 3
            THEN jsonb_set(raw_cells, '{1,1}', '"DIFFERENT"'::jsonb)
            ELSE raw_cells END
FROM retail.source_rows WHERE source_file_sha256 = repeat('E',64);
INSERT INTO retail.invoice_lines
    (source_file_sha256, worksheet, source_row_number, policy_version,
     invoice_no, stock_code, description, quantity, invoice_datetime_raw,
     unit_price_gbp, customer_id, country, classification,
     signed_line_value_gbp)
SELECT repeat('D',64), worksheet, source_row_number, policy_version,
       invoice_no, stock_code, description, quantity, invoice_datetime_raw,
       unit_price_gbp, customer_id, country, classification,
       signed_line_value_gbp
FROM retail.invoice_lines WHERE source_file_sha256 = repeat('E',64);

DO $negative$
DECLARE error_message text;
BEGIN
    BEGIN
        PERFORM * FROM retail.canonical_period_line_keys_v1(
            repeat('D',64), '2010-12-01', '2010-12-03');
        RAISE EXCEPTION 'Mismatched overlap was accepted';
    EXCEPTION WHEN raise_exception THEN
        GET STACKED DIAGNOSTICS error_message = MESSAGE_TEXT;
        IF error_message NOT LIKE 'Annual worksheet overlap differs:%' THEN
            RAISE;
        END IF;
    END;
END
$negative$;

-- Same valid overlap, but a complete older sheet extends past its allowed end.
INSERT INTO retail.source_snapshots
    (source_file_sha256, dataset_id, source_filename, source_bytes,
     source_url, license_name, expected_data_rows)
SELECT repeat('C',64), dataset_id, source_filename, source_bytes,
       source_url, license_name, expected_data_rows + 1
FROM retail.source_snapshots WHERE source_file_sha256 = repeat('E',64);
INSERT INTO retail.source_sheets
    (source_file_sha256, worksheet, sheet_ordinal, original_headers, expected_data_rows)
SELECT repeat('C',64), worksheet, sheet_ordinal, original_headers,
       expected_data_rows + CASE WHEN worksheet = 'Year 2009-2010' THEN 1 ELSE 0 END
FROM retail.source_sheets WHERE source_file_sha256 = repeat('E',64);
INSERT INTO retail.import_jobs
    (job_id, source_file_sha256, idempotency_key, state)
VALUES ('cccccccc-cccc-4ccc-8ccc-cccccccccccc', repeat('C',64),
        'overlap-domain-test', 'completed');
INSERT INTO retail.source_rows
    (source_file_sha256, worksheet, source_row_number,
     first_import_job_id, raw_cells)
SELECT repeat('C',64), worksheet, source_row_number,
       'cccccccc-cccc-4ccc-8ccc-cccccccccccc', raw_cells
FROM retail.source_rows WHERE source_file_sha256 = repeat('E',64);
INSERT INTO retail.source_rows
    (source_file_sha256, worksheet, source_row_number,
     first_import_job_id, raw_cells)
VALUES (repeat('C',64), 'Year 2009-2010', 6,
        'cccccccc-cccc-4ccc-8ccc-cccccccccccc',
        jsonb_build_array(
            jsonb_build_array('str','103'),
            jsonb_build_array('str','LATE'),
            jsonb_build_array('null',''),
            jsonb_build_array('numeric','1'),
            jsonb_build_array('datetime','2010-12-10 10:00:00'),
            jsonb_build_array('numeric','1'),
            jsonb_build_array('str','10'),
            jsonb_build_array('str','UK')));
INSERT INTO retail.invoice_lines
    (source_file_sha256, worksheet, source_row_number, policy_version,
     invoice_no, stock_code, description, quantity, invoice_datetime_raw,
     unit_price_gbp, customer_id, country, classification,
     signed_line_value_gbp)
SELECT repeat('C',64), worksheet, source_row_number, policy_version,
       invoice_no, stock_code, description, quantity, invoice_datetime_raw,
       unit_price_gbp, customer_id, country, classification,
       signed_line_value_gbp
FROM retail.invoice_lines WHERE source_file_sha256 = repeat('E',64);
INSERT INTO retail.invoice_lines
    (source_file_sha256, worksheet, source_row_number, policy_version,
     invoice_no, stock_code, quantity, invoice_datetime_raw,
     unit_price_gbp, customer_id, country, classification,
     signed_line_value_gbp)
VALUES (repeat('C',64), 'Year 2009-2010', 6, 'v1',
        '103', 'LATE', 1, '2010-12-10 10:00', 1, '10', 'UK', 'sale', 1);

DO $domain_negative$
DECLARE error_message text;
BEGIN
    BEGIN
        PERFORM * FROM retail.canonical_period_line_keys_v1(
            repeat('C',64), '2010-12-01', '2010-12-11');
        RAISE EXCEPTION 'Out-of-domain older line was accepted';
    EXCEPTION WHEN raise_exception THEN
        GET STACKED DIAGNOSTICS error_message = MESSAGE_TEXT;
        IF error_message NOT LIKE 'Annual worksheet contains % out-of-domain line(s)' THEN
            RAISE;
        END IF;
    END;
END
$domain_negative$;

SELECT 'PASS|overlap-selection|duplicate-preservation|mismatch-and-domain-rejection';
ROLLBACK;
