-- WP2 migration 001. Apply once, transactionally, to a dedicated application DB.
-- Never apply to the G0/n8n metadata database. No DROP or source-row DELETE exists.

DO $guard$
BEGIN
    IF current_database() = 'n8n' THEN
        RAISE EXCEPTION 'Refusing to install business tables in the n8n metadata database';
    END IF;
END
$guard$;

CREATE SCHEMA retail;

CREATE TABLE retail.schema_migrations (
    version integer PRIMARY KEY,
    name text NOT NULL,
    applied_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE retail.source_snapshots (
    source_file_sha256 text PRIMARY KEY
        CHECK (source_file_sha256 ~ '^[0-9A-F]{64}$'),
    dataset_id text NOT NULL CHECK (length(btrim(dataset_id)) > 0),
    source_filename text NOT NULL CHECK (length(btrim(source_filename)) > 0),
    source_bytes bigint NOT NULL CHECK (source_bytes > 0),
    source_url text NOT NULL CHECK (length(btrim(source_url)) > 0),
    license_name text NOT NULL CHECK (length(btrim(license_name)) > 0),
    expected_data_rows bigint NOT NULL CHECK (expected_data_rows >= 0),
    registered_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE retail.source_sheets (
    source_file_sha256 text NOT NULL
        REFERENCES retail.source_snapshots (source_file_sha256),
    worksheet text NOT NULL CHECK (length(btrim(worksheet)) > 0),
    sheet_ordinal integer NOT NULL CHECK (sheet_ordinal > 0),
    original_headers jsonb NOT NULL
        CHECK (jsonb_typeof(original_headers) = 'array'
               AND jsonb_array_length(original_headers) = 8),
    expected_data_rows bigint NOT NULL CHECK (expected_data_rows >= 0),
    PRIMARY KEY (source_file_sha256, worksheet),
    UNIQUE (source_file_sha256, sheet_ordinal)
);

CREATE TABLE retail.import_jobs (
    job_id uuid PRIMARY KEY,
    source_file_sha256 text NOT NULL
        REFERENCES retail.source_snapshots (source_file_sha256),
    idempotency_key text NOT NULL CHECK (length(btrim(idempotency_key)) > 0),
    state text NOT NULL DEFAULT 'pending'
        CHECK (state IN ('pending', 'running', 'completed', 'failed')),
    rows_seen bigint NOT NULL DEFAULT 0 CHECK (rows_seen >= 0),
    rows_inserted bigint NOT NULL DEFAULT 0 CHECK (rows_inserted >= 0),
    rows_existing bigint NOT NULL DEFAULT 0 CHECK (rows_existing >= 0),
    rows_failed bigint NOT NULL DEFAULT 0 CHECK (rows_failed >= 0),
    started_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at timestamptz,
    UNIQUE (source_file_sha256, idempotency_key),
    UNIQUE (job_id, source_file_sha256),
    CHECK (finished_at IS NULL OR finished_at >= started_at)
);

CREATE TABLE retail.source_rows (
    source_file_sha256 text NOT NULL,
    worksheet text NOT NULL,
    source_row_number integer NOT NULL CHECK (source_row_number >= 2),
    first_import_job_id uuid NOT NULL,
    -- Ordered [[cell_type, textual_cell_value], ...] tokens from the workbook.
    -- The original XLSX remains the byte-for-byte source of record.
    raw_cells jsonb NOT NULL
        CHECK (jsonb_typeof(raw_cells) = 'array'
               AND jsonb_array_length(raw_cells) = 8),
    ingested_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (source_file_sha256, worksheet, source_row_number),
    FOREIGN KEY (source_file_sha256, worksheet)
        REFERENCES retail.source_sheets (source_file_sha256, worksheet),
    FOREIGN KEY (first_import_job_id, source_file_sha256)
        REFERENCES retail.import_jobs (job_id, source_file_sha256)
);

CREATE INDEX source_rows_first_import_job_idx
    ON retail.source_rows (first_import_job_id);

CREATE FUNCTION retail.reject_source_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $function$
BEGIN
    RAISE EXCEPTION 'Source provenance is append-only: % on % is prohibited',
        TG_OP, TG_TABLE_NAME;
END
$function$;

CREATE TRIGGER source_snapshots_immutable
    BEFORE UPDATE OR DELETE ON retail.source_snapshots
    FOR EACH ROW EXECUTE FUNCTION retail.reject_source_mutation();
CREATE TRIGGER source_sheets_immutable
    BEFORE UPDATE OR DELETE ON retail.source_sheets
    FOR EACH ROW EXECUTE FUNCTION retail.reject_source_mutation();
CREATE TRIGGER source_rows_immutable
    BEFORE UPDATE OR DELETE ON retail.source_rows
    FOR EACH ROW EXECUTE FUNCTION retail.reject_source_mutation();

INSERT INTO retail.schema_migrations (version, name)
VALUES (1, 'source_ingest');
