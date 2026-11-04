-- Eight synthetic rows covering policy-v1 branches. Transaction always rolls back.
BEGIN;
INSERT INTO retail.source_snapshots
    (source_file_sha256, dataset_id, source_filename, source_bytes,
     source_url, license_name, expected_data_rows)
VALUES (repeat('D', 64), 'synthetic-test', 'policy.xlsx', 100,
        'https://example.org/policy', 'test-only', 8);
INSERT INTO retail.source_sheets
    (source_file_sha256, worksheet, sheet_ordinal, original_headers, expected_data_rows)
VALUES (repeat('D', 64), 'Policy sheet', 1,
        '["Invoice","StockCode","Description","Quantity","InvoiceDate","Price","Customer ID","Country"]'::jsonb,
        8);
INSERT INTO retail.import_jobs
    (job_id, source_file_sha256, idempotency_key, state,
     rows_seen, rows_inserted, finished_at)
VALUES ('00000000-0000-4000-8000-000000000004', repeat('D', 64),
        'synthetic-policy-v1', 'completed', 8, 8, CURRENT_TIMESTAMP);
INSERT INTO retail.source_rows
    (source_file_sha256, worksheet, source_row_number, first_import_job_id, raw_cells)
VALUES
    (repeat('D', 64), 'Policy sheet', 2, '00000000-0000-4000-8000-000000000004',
     '[["int","100"],["str","P1"],["str","Item"],["int","2"],["datetime","2011-01-01T10:00:00"],["float","1.25"],["null",""],["str","UK"]]'::jsonb),
    (repeat('D', 64), 'Policy sheet', 3, '00000000-0000-4000-8000-000000000004',
     '[["int","101"],["str","P1"],["str","Item"],["int","1"],["datetime","2011-01-01T10:00:00"],["int","0"],["int","1"],["str","UK"]]'::jsonb),
    (repeat('D', 64), 'Policy sheet', 4, '00000000-0000-4000-8000-000000000004',
     '[["str","C102"],["str","P1"],["str","Item"],["int","-1"],["datetime","2011-01-01T10:00:00"],["float","1.25"],["int","1"],["str","UK"]]'::jsonb),
    (repeat('D', 64), 'Policy sheet', 5, '00000000-0000-4000-8000-000000000004',
     '[["int","103"],["str","P1"],["str","Item"],["int","-1"],["datetime","2011-01-01T10:00:00"],["int","2"],["int","1"],["str","UK"]]'::jsonb),
    (repeat('D', 64), 'Policy sheet', 6, '00000000-0000-4000-8000-000000000004',
     '[["int","104"],["str","P1"],["str","Item"],["int","1"],["datetime","2011-01-01T10:00:00"],["int","-5"],["int","1"],["str","UK"]]'::jsonb),
    (repeat('D', 64), 'Policy sheet', 7, '00000000-0000-4000-8000-000000000004',
     '[["int","105"],["str","P1"],["str","Item"],["int","0"],["datetime","2011-01-01T10:00:00"],["int","3"],["int","1"],["str","UK"]]'::jsonb),
    (repeat('D', 64), 'Policy sheet', 8, '00000000-0000-4000-8000-000000000004',
     '[["int","106"],["str","P1"],["null",""],["int","1"],["datetime","2011-01-01T10:00:00"],["int","3"],["int","2"],["str","UK"]]'::jsonb),
    (repeat('D', 64), 'Policy sheet', 9, '00000000-0000-4000-8000-000000000004',
     '[["null",""],["str","P1"],["str","Item"],["int","1"],["datetime","2011-01-01T10:00:00"],["int","1"],["int","3"],["str","UK"]]'::jsonb);

SELECT * FROM retail.classify_snapshot_v1(repeat('D', 64));

DO $test$
BEGIN
    IF (SELECT count(*) FROM retail.invoice_lines
        WHERE source_file_sha256 = repeat('D', 64)) <> 8 THEN
        RAISE EXCEPTION 'Not every physical source row was classified';
    END IF;
    IF (SELECT count(*) FROM retail.invoice_lines
        WHERE source_file_sha256 = repeat('D', 64)
          AND classification = 'sale') <> 3 THEN
        RAISE EXCEPTION 'Sale classification or missing-customer retention failed';
    END IF;
    IF (SELECT sum(signed_line_value_gbp) FROM retail.invoice_lines
        WHERE source_file_sha256 = repeat('D', 64)
          AND classification = 'sale') <> 5.5::numeric THEN
        RAISE EXCEPTION 'Exact sale money failed';
    END IF;
    IF (SELECT sum(signed_line_value_gbp) FROM retail.invoice_lines
        WHERE source_file_sha256 = repeat('D', 64)
          AND classification = 'cancellation') <> -1.25::numeric THEN
        RAISE EXCEPTION 'Cancellation value failed';
    END IF;
    IF (SELECT count(*) FROM retail.invoice_lines
        WHERE source_file_sha256 = repeat('D', 64)
          AND classification = 'other_adjustment') <> 1 OR
       (SELECT count(*) FROM retail.invoice_lines
        WHERE source_file_sha256 = repeat('D', 64)
          AND classification = 'zero_quantity_non_sales') <> 1 OR
       (SELECT count(*) FROM retail.invoice_lines
        WHERE source_file_sha256 = repeat('D', 64)
          AND classification = 'invalid') <> 2 THEN
        RAISE EXCEPTION 'Exception-class counts failed';
    END IF;
    IF (SELECT count(*) FROM retail.quality_findings
        WHERE source_file_sha256 = repeat('D', 64)) <> 7 THEN
        RAISE EXCEPTION 'Quality finding count failed';
    END IF;
    IF (SELECT signed_line_value_gbp FROM retail.quality_findings
        WHERE source_file_sha256 = repeat('D', 64)
          AND finding_code = 'negative_unit_price') <> -5::numeric THEN
        RAISE EXCEPTION 'Invalid monetary impact was not preserved';
    END IF;
END
$test$;
ROLLBACK;
