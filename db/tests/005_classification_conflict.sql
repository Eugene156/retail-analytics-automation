-- Negative test: a changed v1 classification for the same physical row fails.
-- ON_ERROR_STOP exits on the expected error; the connection rolls back.
BEGIN;
INSERT INTO retail.source_snapshots
    (source_file_sha256, dataset_id, source_filename, source_bytes,
     source_url, license_name, expected_data_rows)
VALUES (repeat('E', 64), 'synthetic-test', 'conflict.xlsx', 100,
        'https://example.org/conflict', 'test-only', 1);
INSERT INTO retail.source_sheets
    (source_file_sha256, worksheet, sheet_ordinal, original_headers, expected_data_rows)
VALUES (repeat('E', 64), 'Conflict sheet', 1,
        '["Invoice","StockCode","Description","Quantity","InvoiceDate","Price","Customer ID","Country"]'::jsonb,
        1);
INSERT INTO retail.import_jobs
    (job_id, source_file_sha256, idempotency_key, state,
     rows_seen, rows_inserted, finished_at)
VALUES ('00000000-0000-4000-8000-000000000005', repeat('E', 64),
        'synthetic-classification-conflict', 'completed', 1, 1, CURRENT_TIMESTAMP);
INSERT INTO retail.source_rows
    (source_file_sha256, worksheet, source_row_number, first_import_job_id, raw_cells)
VALUES (repeat('E', 64), 'Conflict sheet', 2,
        '00000000-0000-4000-8000-000000000005',
        '[["str","C100"],["str","P1"],["str","Item"],["int","-1"],["datetime","2011-01-01T10:00:00"],["float","1.25"],["int","1"],["str","UK"]]'::jsonb);

-- The source requires cancellation, but an existing v1 line says adjustment.
INSERT INTO retail.invoice_lines
    (source_file_sha256, worksheet, source_row_number, policy_version,
     invoice_no, stock_code, description, quantity, invoice_datetime_raw,
     unit_price_gbp, customer_id, country, classification,
     signed_line_value_gbp)
VALUES (repeat('E', 64), 'Conflict sheet', 2, 'v1',
        'C100', 'P1', 'Item', -1, '2011-01-01T10:00:00'::timestamp,
        1.25, '1', 'UK', 'other_adjustment', -1.25);

SELECT * FROM retail.classify_snapshot_v1(repeat('E', 64));
