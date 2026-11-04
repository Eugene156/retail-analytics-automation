-- Append after 002_import_finalize_setup.sql, then import_finalize.sql must fail.
-- The connection rollback leaves no synthetic rows.
INSERT INTO retail.source_snapshots
    (source_file_sha256, dataset_id, source_filename, source_bytes,
     source_url, license_name, expected_data_rows)
SELECT source_file_sha256, dataset_id, source_filename, source_bytes,
       source_url, license_name, expected_data_rows
FROM stage_snapshot;

INSERT INTO retail.source_sheets
    (source_file_sha256, worksheet, sheet_ordinal, original_headers, expected_data_rows)
SELECT source_file_sha256, worksheet, sheet_ordinal, original_headers, expected_data_rows
FROM stage_sheets;

INSERT INTO retail.import_jobs
    (job_id, source_file_sha256, idempotency_key, state,
     rows_seen, rows_inserted, finished_at)
SELECT j.job_id, s.source_file_sha256, j.idempotency_key,
       'completed', 2, 2, CURRENT_TIMESTAMP
FROM stage_job j CROSS JOIN stage_snapshot s;

INSERT INTO retail.source_rows
    (source_file_sha256, worksheet, source_row_number,
     first_import_job_id, raw_cells)
SELECT r.source_file_sha256, r.worksheet, r.source_row_number,
       j.job_id,
       CASE WHEN r.source_row_number = 2
            THEN jsonb_set(r.raw_cells, '{5,1}', '"999"'::jsonb)
            ELSE r.raw_cells END
FROM stage_rows r CROSS JOIN stage_job j;
