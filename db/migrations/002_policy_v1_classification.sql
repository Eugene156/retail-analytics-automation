-- WP2 migration 002. Apply once and transactionally after migration 001.
-- Derived rows are versioned and append-only; raw source rows stay untouched.

DO $guard$
BEGIN
    IF current_database() = 'n8n' THEN
        RAISE EXCEPTION 'Refusing to install business tables in the n8n metadata database';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM retail.schema_migrations WHERE version = 1) THEN
        RAISE EXCEPTION 'Migration 001 is required first';
    END IF;
END
$guard$;

CREATE TABLE retail.invoice_lines (
    source_file_sha256 text NOT NULL,
    worksheet text NOT NULL,
    source_row_number integer NOT NULL,
    policy_version text NOT NULL CHECK (policy_version = 'v1'),
    invoice_no text,
    stock_code text,
    description text,
    quantity numeric,
    invoice_datetime_raw timestamp without time zone,
    unit_price_gbp numeric,
    customer_id text,
    country text,
    classification text NOT NULL CHECK (classification IN (
        'sale', 'cancellation', 'other_adjustment',
        'zero_quantity_non_sales', 'invalid'
    )),
    signed_line_value_gbp numeric,
    classified_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (source_file_sha256, worksheet, source_row_number, policy_version),
    FOREIGN KEY (source_file_sha256, worksheet, source_row_number)
        REFERENCES retail.source_rows
            (source_file_sha256, worksheet, source_row_number),
    CHECK (signed_line_value_gbp IS NOT DISTINCT FROM quantity * unit_price_gbp)
);

CREATE INDEX invoice_lines_policy_class_time_idx
    ON retail.invoice_lines
        (source_file_sha256, policy_version, classification, invoice_datetime_raw);

CREATE TABLE retail.quality_findings (
    source_file_sha256 text NOT NULL,
    worksheet text NOT NULL,
    source_row_number integer NOT NULL,
    policy_version text NOT NULL,
    finding_code text NOT NULL CHECK (finding_code IN (
        'missing_invoice', 'missing_stock_code', 'invalid_invoice_datetime',
        'invalid_quantity', 'invalid_unit_price', 'negative_unit_price',
        'zero_quantity', 'negative_quantity_without_c',
        'c_invoice_non_negative_quantity', 'missing_customer_id',
        'missing_description', 'zero_price_sale'
    )),
    severity text NOT NULL CHECK (severity IN ('invalid', 'warning')),
    signed_line_value_gbp numeric,
    recorded_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (source_file_sha256, worksheet, source_row_number,
                 policy_version, finding_code),
    FOREIGN KEY (source_file_sha256, worksheet, source_row_number,
                 policy_version)
        REFERENCES retail.invoice_lines
            (source_file_sha256, worksheet, source_row_number, policy_version)
);

CREATE INDEX quality_findings_policy_code_idx
    ON retail.quality_findings (source_file_sha256, policy_version, finding_code);

CREATE TRIGGER invoice_lines_immutable
    BEFORE UPDATE OR DELETE ON retail.invoice_lines
    FOR EACH ROW EXECUTE FUNCTION retail.reject_source_mutation();
CREATE TRIGGER quality_findings_immutable
    BEFORE UPDATE OR DELETE ON retail.quality_findings
    FOR EACH ROW EXECUTE FUNCTION retail.reject_source_mutation();

CREATE FUNCTION retail.cell_value(cells jsonb, cell_index integer)
RETURNS text
LANGUAGE sql IMMUTABLE PARALLEL SAFE
AS $function$
    SELECT CASE WHEN cells->cell_index->>0 = 'null' THEN NULL
                ELSE cells->cell_index->>1 END
$function$;

CREATE FUNCTION retail.try_numeric(source_text text)
RETURNS numeric
LANGUAGE plpgsql IMMUTABLE PARALLEL SAFE
AS $function$
BEGIN
    IF source_text IS NULL OR btrim(source_text) !~
        '^[+-]?([0-9]+(\.[0-9]*)?|\.[0-9]+)([eE][+-]?[0-9]+)?$' THEN
        RETURN NULL;
    END IF;
    RETURN source_text::numeric;
EXCEPTION WHEN invalid_text_representation OR numeric_value_out_of_range THEN
    RETURN NULL;
END
$function$;

CREATE FUNCTION retail.try_source_timestamp(source_text text)
RETURNS timestamp without time zone
LANGUAGE plpgsql STABLE PARALLEL SAFE
AS $function$
BEGIN
    IF source_text IS NULL OR source_text !~
        '^[0-9]{4}-[0-9]{2}-[0-9]{2}([T ][0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]+)?)?$' THEN
        RETURN NULL;
    END IF;
    RETURN source_text::timestamp without time zone;
EXCEPTION WHEN invalid_datetime_format OR datetime_field_overflow THEN
    RETURN NULL;
END
$function$;

CREATE FUNCTION retail.classify_snapshot_v1(snapshot_hash text)
RETURNS TABLE (source_row_count bigint, normalized_row_count bigint,
               new_line_count bigint, quality_finding_count bigint)
LANGUAGE plpgsql
AS $function$
DECLARE
    expected_rows bigint;
    inserted_lines bigint;
    stored_lines bigint;
    stored_findings bigint;
BEGIN
    SELECT expected_data_rows INTO expected_rows
    FROM retail.source_snapshots WHERE source_file_sha256 = snapshot_hash;
    IF expected_rows IS NULL THEN
        RAISE EXCEPTION 'Unknown source snapshot';
    END IF;
    IF (SELECT count(*) FROM retail.source_rows
        WHERE source_file_sha256 = snapshot_hash) <> expected_rows THEN
        RAISE EXCEPTION 'Raw source rows do not reconcile';
    END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended(snapshot_hash, 1));

    CREATE TEMP TABLE wp2_stage_lines ON COMMIT DROP AS
    WITH extracted AS (
        SELECT s.source_file_sha256, s.worksheet, s.source_row_number,
               NULLIF(btrim(retail.cell_value(s.raw_cells, 0)), '') AS invoice_no,
               NULLIF(btrim(retail.cell_value(s.raw_cells, 1)), '') AS stock_code,
               NULLIF(btrim(retail.cell_value(s.raw_cells, 2)), '') AS description,
               retail.try_numeric(retail.cell_value(s.raw_cells, 3)) AS quantity,
               retail.try_source_timestamp(retail.cell_value(s.raw_cells, 4))
                   AS invoice_datetime_raw,
               retail.try_numeric(retail.cell_value(s.raw_cells, 5)) AS unit_price_gbp,
               NULLIF(btrim(retail.cell_value(s.raw_cells, 6)), '') AS customer_id,
               NULLIF(btrim(retail.cell_value(s.raw_cells, 7)), '') AS country
        FROM retail.source_rows s
        WHERE s.source_file_sha256 = snapshot_hash
    )
    SELECT e.*, 'v1'::text AS policy_version,
           CASE
             WHEN e.invoice_no IS NULL OR e.stock_code IS NULL
               OR e.invoice_datetime_raw IS NULL OR e.quantity IS NULL
               OR e.unit_price_gbp IS NULL OR e.unit_price_gbp < 0
               THEN 'invalid'
             WHEN e.quantity = 0 THEN 'zero_quantity_non_sales'
             WHEN upper(e.invoice_no) LIKE 'C%' AND e.quantity < 0
               THEN 'cancellation'
             WHEN upper(e.invoice_no) NOT LIKE 'C%' AND e.quantity > 0
               THEN 'sale'
             ELSE 'other_adjustment'
           END::text AS classification,
           e.quantity * e.unit_price_gbp AS signed_line_value_gbp
    FROM extracted e;

    IF (SELECT count(*) FROM wp2_stage_lines) <> expected_rows THEN
        RAISE EXCEPTION 'Normalized stage count mismatch';
    END IF;

    INSERT INTO retail.invoice_lines
        (source_file_sha256, worksheet, source_row_number, policy_version,
         invoice_no, stock_code, description, quantity, invoice_datetime_raw,
         unit_price_gbp, customer_id, country, classification,
         signed_line_value_gbp)
    SELECT source_file_sha256, worksheet, source_row_number, policy_version,
           invoice_no, stock_code, description, quantity, invoice_datetime_raw,
           unit_price_gbp, customer_id, country, classification,
           signed_line_value_gbp
    FROM wp2_stage_lines
    ON CONFLICT (source_file_sha256, worksheet, source_row_number, policy_version)
        DO NOTHING;
    GET DIAGNOSTICS inserted_lines = ROW_COUNT;

    IF EXISTS (
        SELECT 1 FROM wp2_stage_lines s
        JOIN retail.invoice_lines r USING
            (source_file_sha256, worksheet, source_row_number, policy_version)
        WHERE ROW(r.invoice_no, r.stock_code, r.description, r.quantity,
                  r.invoice_datetime_raw, r.unit_price_gbp, r.customer_id,
                  r.country, r.classification, r.signed_line_value_gbp)
              IS DISTINCT FROM
              ROW(s.invoice_no, s.stock_code, s.description, s.quantity,
                  s.invoice_datetime_raw, s.unit_price_gbp, s.customer_id,
                  s.country, s.classification, s.signed_line_value_gbp)
    ) THEN
        RAISE EXCEPTION 'Existing normalized row differs under policy v1';
    END IF;
    SELECT count(*) INTO stored_lines FROM retail.invoice_lines
    WHERE source_file_sha256 = snapshot_hash AND policy_version = 'v1';
    IF stored_lines <> expected_rows THEN
        RAISE EXCEPTION 'Stored normalized rows do not reconcile';
    END IF;

    CREATE TEMP TABLE wp2_stage_findings ON COMMIT DROP AS
    SELECT l.source_file_sha256, l.worksheet, l.source_row_number,
           l.policy_version, f.finding_code, f.severity,
           l.signed_line_value_gbp
    FROM wp2_stage_lines l
    CROSS JOIN LATERAL (VALUES
        ('missing_invoice', 'invalid', l.invoice_no IS NULL),
        ('missing_stock_code', 'invalid', l.stock_code IS NULL),
        ('invalid_invoice_datetime', 'invalid', l.invoice_datetime_raw IS NULL),
        ('invalid_quantity', 'invalid', l.quantity IS NULL),
        ('invalid_unit_price', 'invalid', l.unit_price_gbp IS NULL),
        ('negative_unit_price', 'invalid', l.unit_price_gbp < 0),
        ('zero_quantity', 'warning', l.classification = 'zero_quantity_non_sales'),
        ('negative_quantity_without_c', 'warning',
             l.classification = 'other_adjustment'
             AND upper(l.invoice_no) NOT LIKE 'C%' AND l.quantity < 0),
        ('c_invoice_non_negative_quantity', 'warning',
             l.classification = 'other_adjustment'
             AND upper(l.invoice_no) LIKE 'C%' AND l.quantity >= 0),
        ('missing_customer_id', 'warning', l.customer_id IS NULL),
        ('missing_description', 'warning', l.description IS NULL),
        ('zero_price_sale', 'warning',
             l.classification = 'sale' AND l.unit_price_gbp = 0)
    ) AS f(finding_code, severity, applies)
    WHERE f.applies;

    INSERT INTO retail.quality_findings
        (source_file_sha256, worksheet, source_row_number, policy_version,
         finding_code, severity, signed_line_value_gbp)
    SELECT source_file_sha256, worksheet, source_row_number, policy_version,
           finding_code, severity, signed_line_value_gbp
    FROM wp2_stage_findings
    ON CONFLICT (source_file_sha256, worksheet, source_row_number,
                 policy_version, finding_code) DO NOTHING;

    IF EXISTS (
        SELECT 1 FROM wp2_stage_findings s
        JOIN retail.quality_findings r USING
            (source_file_sha256, worksheet, source_row_number,
             policy_version, finding_code)
        WHERE ROW(r.severity, r.signed_line_value_gbp)
              IS DISTINCT FROM ROW(s.severity, s.signed_line_value_gbp)
    ) THEN
        RAISE EXCEPTION 'Existing quality finding differs under policy v1';
    END IF;
    SELECT count(*) INTO stored_findings FROM retail.quality_findings
    WHERE source_file_sha256 = snapshot_hash AND policy_version = 'v1';
    IF stored_findings <> (SELECT count(*) FROM wp2_stage_findings) THEN
        RAISE EXCEPTION 'Stored quality findings do not reconcile';
    END IF;

    RETURN QUERY SELECT expected_rows, stored_lines, inserted_lines, stored_findings;
END
$function$;

INSERT INTO retail.schema_migrations (version, name)
VALUES (2, 'policy_v1_classification');
