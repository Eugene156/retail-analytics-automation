-- Executed after a complete read-only workbook stream to temporary stage tables.
-- The caller owns BEGIN/COMMIT and must set ON_ERROR_STOP=1. No source mutations.

DO $validate_stage$
DECLARE
    snapshot_count bigint;
    sheet_count bigint;
    job_count bigint;
    staged_rows bigint;
    expected_rows bigint;
BEGIN
    SELECT count(*), max(expected_data_rows)
      INTO snapshot_count, expected_rows FROM stage_snapshot;
    SELECT count(*) INTO sheet_count FROM stage_sheets;
    SELECT count(*) INTO job_count FROM stage_job;
    SELECT count(*) INTO staged_rows FROM stage_rows;
    IF snapshot_count <> 1 OR sheet_count <> 2 OR job_count <> 1 THEN
        RAISE EXCEPTION 'Unexpected staged metadata cardinality';
    END IF;
    IF staged_rows <> expected_rows THEN
        RAISE EXCEPTION 'Staged source-row count mismatch';
    END IF;
    IF (SELECT sum(expected_data_rows) FROM stage_sheets) <> expected_rows THEN
        RAISE EXCEPTION 'Worksheet expectations do not reconcile';
    END IF;
    IF EXISTS (
        SELECT 1 FROM stage_sheets s
        LEFT JOIN (
            SELECT worksheet, count(*) AS actual_rows
            FROM stage_rows GROUP BY worksheet
        ) r USING (worksheet)
        WHERE s.expected_data_rows <> coalesce(r.actual_rows, 0)
    ) OR EXISTS (
        SELECT 1 FROM stage_rows r
        LEFT JOIN stage_sheets s USING (worksheet)
        WHERE s.worksheet IS NULL
    ) THEN
        RAISE EXCEPTION 'Staged worksheet row-count mismatch';
    END IF;
    IF EXISTS (
        SELECT 1 FROM stage_rows r CROSS JOIN stage_snapshot s
        WHERE r.source_file_sha256 <> s.source_file_sha256
    ) OR EXISTS (
        SELECT 1 FROM stage_sheets sh CROSS JOIN stage_snapshot s
        WHERE sh.source_file_sha256 <> s.source_file_sha256
    ) THEN
        RAISE EXCEPTION 'Staged snapshot identity mismatch';
    END IF;
END
$validate_stage$;

CREATE UNIQUE INDEX stage_rows_identity_idx
    ON stage_rows (source_file_sha256, worksheet, source_row_number);

-- Serialize this source snapshot's finalize phase, including replay comparison.
DO $lock_snapshot$
DECLARE
    snapshot_hash text;
BEGIN
    SELECT source_file_sha256 INTO STRICT snapshot_hash FROM stage_snapshot;
    PERFORM pg_advisory_xact_lock(hashtextextended(snapshot_hash, 0));
END
$lock_snapshot$;

INSERT INTO retail.source_snapshots
    (source_file_sha256, dataset_id, source_filename, source_bytes,
     source_url, license_name, expected_data_rows)
SELECT source_file_sha256, dataset_id, source_filename, source_bytes,
       source_url, license_name, expected_data_rows
FROM stage_snapshot
ON CONFLICT (source_file_sha256) DO NOTHING;

DO $check_snapshot$
BEGIN
    IF EXISTS (
        SELECT 1 FROM stage_snapshot s
        JOIN retail.source_snapshots r USING (source_file_sha256)
        WHERE ROW(r.dataset_id, r.source_filename, r.source_bytes, r.source_url,
                  r.license_name, r.expected_data_rows)
              IS DISTINCT FROM
              ROW(s.dataset_id, s.source_filename, s.source_bytes, s.source_url,
                  s.license_name, s.expected_data_rows)
    ) THEN
        RAISE EXCEPTION 'Existing snapshot metadata mismatch';
    END IF;
END
$check_snapshot$;

INSERT INTO retail.source_sheets
    (source_file_sha256, worksheet, sheet_ordinal, original_headers, expected_data_rows)
SELECT source_file_sha256, worksheet, sheet_ordinal, original_headers, expected_data_rows
FROM stage_sheets
ON CONFLICT (source_file_sha256, worksheet) DO NOTHING;

DO $check_sheets$
BEGIN
    IF EXISTS (
        SELECT 1 FROM stage_sheets s
        JOIN retail.source_sheets r USING (source_file_sha256, worksheet)
        WHERE ROW(r.sheet_ordinal, r.original_headers, r.expected_data_rows)
              IS DISTINCT FROM
              ROW(s.sheet_ordinal, s.original_headers, s.expected_data_rows)
    ) OR (
        SELECT count(*) FROM retail.source_sheets r
        JOIN stage_snapshot s USING (source_file_sha256)
    ) <> (SELECT count(*) FROM stage_sheets) THEN
        RAISE EXCEPTION 'Existing worksheet metadata mismatch';
    END IF;
END
$check_sheets$;

INSERT INTO retail.import_jobs
    (job_id, source_file_sha256, idempotency_key, state)
SELECT j.job_id, s.source_file_sha256, j.idempotency_key, 'running'
FROM stage_job j CROSS JOIN stage_snapshot s
ON CONFLICT (source_file_sha256, idempotency_key) DO NOTHING;

DO $check_job$
BEGIN
    IF EXISTS (
        SELECT 1 FROM stage_job j CROSS JOIN stage_snapshot s
        JOIN retail.import_jobs r
          ON r.source_file_sha256 = s.source_file_sha256
         AND r.idempotency_key = j.idempotency_key
        WHERE r.job_id <> j.job_id AND r.state <> 'completed'
    ) THEN
        RAISE EXCEPTION 'Existing idempotency key is not completed';
    END IF;
    IF EXISTS (
        SELECT 1 FROM stage_job j CROSS JOIN stage_snapshot s
        JOIN retail.import_jobs r
          ON r.source_file_sha256 = s.source_file_sha256
         AND r.idempotency_key = j.idempotency_key
        WHERE r.job_id <> j.job_id
          AND r.state = 'completed'
          AND (SELECT count(*) FROM retail.source_rows source
               WHERE source.source_file_sha256 = s.source_file_sha256)
              <> s.expected_data_rows
    ) THEN
        RAISE EXCEPTION 'Completed import job has incomplete source rows';
    END IF;
END
$check_job$;

-- A conflicting physical identity must have identical typed cell tokens.
DO $check_payload$
BEGIN
    IF EXISTS (
        SELECT 1 FROM stage_rows s
        JOIN retail.source_rows r
          ON r.source_file_sha256 = s.source_file_sha256
         AND r.worksheet = s.worksheet
         AND r.source_row_number = s.source_row_number
        WHERE r.raw_cells IS DISTINCT FROM s.raw_cells
    ) THEN
        RAISE EXCEPTION 'Existing physical source row has changed payload';
    END IF;
END
$check_payload$;

-- Count actual inserts, not a pre-insert estimate. Equal-valued rows with
-- different row numbers remain separate because the conflict key is physical.
CREATE TEMP TABLE import_inserted ON COMMIT DROP AS
WITH inserted AS (
    INSERT INTO retail.source_rows
        (source_file_sha256, worksheet, source_row_number,
         first_import_job_id, raw_cells)
    SELECT s.source_file_sha256, s.worksheet, s.source_row_number,
           j.job_id, s.raw_cells
    FROM stage_rows s, stage_job input_job, retail.import_jobs j
    WHERE j.source_file_sha256 = s.source_file_sha256
      AND j.idempotency_key = input_job.idempotency_key
    ON CONFLICT (source_file_sha256, worksheet, source_row_number) DO NOTHING
    RETURNING 1 AS inserted_row
)
SELECT count(*)::bigint AS inserted_count FROM inserted;

DO $check_final$
DECLARE
    source_hash text;
    expected_rows bigint;
    actual_rows bigint;
    inserted_rows bigint;
BEGIN
    SELECT source_file_sha256, expected_data_rows
      INTO STRICT source_hash, expected_rows FROM stage_snapshot;
    SELECT count(*) INTO actual_rows FROM retail.source_rows
    WHERE source_file_sha256 = source_hash;
    SELECT inserted_count INTO STRICT inserted_rows FROM import_inserted;
    IF actual_rows <> expected_rows THEN
        RAISE EXCEPTION 'Stored source-row count does not reconcile';
    END IF;
    IF inserted_rows < 0 OR inserted_rows > expected_rows THEN
        RAISE EXCEPTION 'Invalid inserted-row count';
    END IF;
END
$check_final$;

UPDATE retail.import_jobs r
SET state = 'completed',
    rows_seen = (SELECT expected_data_rows FROM stage_snapshot),
    rows_inserted = (SELECT inserted_count FROM import_inserted),
    rows_existing = (SELECT expected_data_rows FROM stage_snapshot)
                    - (SELECT inserted_count FROM import_inserted),
    rows_failed = 0,
    finished_at = CURRENT_TIMESTAMP
FROM stage_job j, stage_snapshot s
WHERE r.job_id = j.job_id
  AND r.source_file_sha256 = s.source_file_sha256
  AND r.state = 'running';

SELECT 'IMPORT_RESULT|' ||
       CASE WHEN r.job_id = j.job_id THEN 'new' ELSE 'idempotent_replay' END || '|' ||
       (SELECT inserted_count FROM import_inserted)::text || '|' ||
       r.rows_seen::text || '|' || r.state
FROM stage_job j CROSS JOIN stage_snapshot s
JOIN retail.import_jobs r
  ON r.source_file_sha256 = s.source_file_sha256
 AND r.idempotency_key = j.idempotency_key;
