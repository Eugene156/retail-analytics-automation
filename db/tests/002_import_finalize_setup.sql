-- Synthetic setup for an isolated, rollback-only test of import_finalize.sql.
BEGIN;
CREATE TEMP TABLE stage_snapshot ON COMMIT DROP AS
SELECT repeat('C', 64)::text AS source_file_sha256,
       'synthetic-test'::text AS dataset_id,
       'tiny.xlsx'::text AS source_filename,
       100::bigint AS source_bytes,
       'https://example.org/tiny'::text AS source_url,
       'test-only'::text AS license_name,
       2::bigint AS expected_data_rows;

CREATE TEMP TABLE stage_sheets ON COMMIT DROP AS
SELECT repeat('C', 64)::text AS source_file_sha256,
       'First sheet'::text AS worksheet,
       1::integer AS sheet_ordinal,
       '["Invoice","StockCode","Description","Quantity","InvoiceDate","Price","Customer ID","Country"]'::jsonb AS original_headers,
       2::bigint AS expected_data_rows
UNION ALL
SELECT repeat('C', 64), 'Second sheet', 2,
       '["Invoice","StockCode","Description","Quantity","InvoiceDate","Price","Customer ID","Country"]'::jsonb,
       0::bigint;

CREATE TEMP TABLE stage_job ON COMMIT DROP AS
SELECT '00000000-0000-4000-8000-000000000002'::uuid AS job_id,
       'synthetic-finalize-test'::text AS idempotency_key;

CREATE TEMP TABLE stage_rows ON COMMIT DROP AS
SELECT repeat('C', 64)::text AS source_file_sha256,
       'First sheet'::text AS worksheet,
       2::integer AS source_row_number,
       '[["int","100"],["str","P1"],["str","Item"],["int","1"],["datetime","2011-01-01T10:00:00"],["float","2.5"],["null",""],["str","United Kingdom"]]'::jsonb AS raw_cells
UNION ALL
SELECT repeat('C', 64), 'First sheet', 3,
       '[["int","100"],["str","P1"],["str","Item"],["int","1"],["datetime","2011-01-01T10:00:00"],["float","2.5"],["null",""],["str","United Kingdom"]]'::jsonb;
