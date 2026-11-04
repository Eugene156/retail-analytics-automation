-- Synthetic transactional smoke test for migration 001. Leaves no fixture rows.
-- Run only after migration 001 in an isolated application test database.
BEGIN;

INSERT INTO retail.source_snapshots
    (source_file_sha256, dataset_id, source_filename, source_bytes,
     source_url, license_name, expected_data_rows)
VALUES
    (repeat('A', 64), 'synthetic-test', 'synthetic.xlsx', 100,
     'https://example.org/synthetic', 'test-only', 2);

INSERT INTO retail.source_sheets
    (source_file_sha256, worksheet, sheet_ordinal, original_headers, expected_data_rows)
VALUES
    (repeat('A', 64), 'Synthetic sheet', 1,
     '["Invoice","StockCode","Description","Quantity","InvoiceDate","Price","Customer ID","Country"]'::jsonb,
     2);

INSERT INTO retail.source_snapshots
    (source_file_sha256, dataset_id, source_filename, source_bytes,
     source_url, license_name, expected_data_rows)
VALUES
    (repeat('B', 64), 'synthetic-test', 'other.xlsx', 100,
     'https://example.org/other', 'test-only', 1);
INSERT INTO retail.source_sheets
    (source_file_sha256, worksheet, sheet_ordinal, original_headers, expected_data_rows)
VALUES
    (repeat('B', 64), 'Other sheet', 1,
     '["Invoice","StockCode","Description","Quantity","InvoiceDate","Price","Customer ID","Country"]'::jsonb,
     1);

INSERT INTO retail.import_jobs (job_id, source_file_sha256, idempotency_key)
VALUES ('00000000-0000-4000-8000-000000000001', repeat('A', 64), 'synthetic-first');

-- Equal cell values are distinct physical source rows. Null customer is retained.
INSERT INTO retail.source_rows
    (source_file_sha256, worksheet, source_row_number, first_import_job_id, raw_cells)
VALUES
    (repeat('A', 64), 'Synthetic sheet', 2,
     '00000000-0000-4000-8000-000000000001',
     '[["int","100"],["str","P1"],["str","Item"],["int","1"],["datetime","2011-01-01T10:00:00"],["float","2.5"],["null",""],["str","United Kingdom"]]'::jsonb),
    (repeat('A', 64), 'Synthetic sheet', 3,
     '00000000-0000-4000-8000-000000000001',
     '[["int","100"],["str","P1"],["str","Item"],["int","1"],["datetime","2011-01-01T10:00:00"],["float","2.5"],["null",""],["str","United Kingdom"]]'::jsonb);

-- A replay of the same physical identity inserts nothing; both original rows survive.
INSERT INTO retail.source_rows
    (source_file_sha256, worksheet, source_row_number, first_import_job_id, raw_cells)
SELECT source_file_sha256, worksheet, source_row_number, first_import_job_id, raw_cells
FROM retail.source_rows
WHERE source_file_sha256 = repeat('A', 64) AND source_row_number = 2
ON CONFLICT (source_file_sha256, worksheet, source_row_number) DO NOTHING;

DO $test$
DECLARE
    blocked boolean := false;
    wrong_job_blocked boolean := false;
    snapshot_blocked boolean := false;
BEGIN
    IF (SELECT count(*) FROM retail.source_rows
        WHERE source_file_sha256 = repeat('A', 64)) <> 2 THEN
        RAISE EXCEPTION 'Physical source-row identity or replay behavior failed';
    END IF;
    IF (SELECT count(DISTINCT raw_cells) FROM retail.source_rows
        WHERE source_file_sha256 = repeat('A', 64)) <> 1 THEN
        RAISE EXCEPTION 'Fixture did not exercise equal-valued distinct rows';
    END IF;
    BEGIN
        UPDATE retail.source_rows SET source_row_number = 4
        WHERE source_file_sha256 = repeat('A', 64) AND source_row_number = 2;
    EXCEPTION WHEN raise_exception THEN
        blocked := true;
    END;
    IF NOT blocked THEN
        RAISE EXCEPTION 'Source rows can be mutated';
    END IF;
    BEGIN
        INSERT INTO retail.source_rows
            (source_file_sha256, worksheet, source_row_number, first_import_job_id, raw_cells)
        VALUES
            (repeat('B', 64), 'Other sheet', 2,
             '00000000-0000-4000-8000-000000000001',
             '[["null",""],["null",""],["null",""],["null",""],["null",""],["null",""],["null",""],["null",""]]'::jsonb);
    EXCEPTION WHEN foreign_key_violation THEN
        wrong_job_blocked := true;
    END;
    IF NOT wrong_job_blocked THEN
        RAISE EXCEPTION 'An import job can claim a row from another snapshot';
    END IF;
    BEGIN
        UPDATE retail.source_snapshots SET source_bytes = 101
        WHERE source_file_sha256 = repeat('A', 64);
    EXCEPTION WHEN raise_exception THEN
        snapshot_blocked := true;
    END;
    IF NOT snapshot_blocked THEN
        RAISE EXCEPTION 'Source snapshot metadata can be mutated';
    END IF;
END
$test$;

ROLLBACK;
