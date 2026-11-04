-- WP2 migration 007. Prevent a nominally complete but out-of-domain sheet
-- from silently losing rows under the migration-006 analytical cutover.
DO $guard$
BEGIN
    IF current_database() = 'n8n' THEN
        RAISE EXCEPTION 'Refusing to install business functions in n8n metadata DB';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM retail.schema_migrations WHERE version = 6) THEN
        RAISE EXCEPTION 'Migration 006 is required first';
    END IF;
END
$guard$;

CREATE FUNCTION retail.assert_uci_502_sheet_domain_v1(p_source_file_sha256 text)
RETURNS void
LANGUAGE plpgsql
STABLE
AS $function$
DECLARE
    snapshot_rows bigint;
    sheet_count bigint;
    sheet_rows bigint;
    valid_sheet_metadata boolean;
    outside_domain_rows bigint;
BEGIN
    SELECT s.expected_data_rows INTO snapshot_rows
    FROM retail.source_snapshots s
    WHERE s.source_file_sha256 = p_source_file_sha256;
    SELECT count(*), coalesce(sum(s.expected_data_rows), 0),
           coalesce(bool_and(
               (s.worksheet = 'Year 2009-2010' AND s.sheet_ordinal = 1)
               OR (s.worksheet = 'Year 2010-2011' AND s.sheet_ordinal = 2)
           ), false)
    INTO sheet_count, sheet_rows, valid_sheet_metadata
    FROM retail.source_sheets s
    WHERE s.source_file_sha256 = p_source_file_sha256;
    IF snapshot_rows IS NULL OR sheet_count <> 2
       OR NOT valid_sheet_metadata OR sheet_rows <> snapshot_rows THEN
        RAISE EXCEPTION 'Annual worksheet metadata does not match the source snapshot';
    END IF;

    SELECT count(*) INTO outside_domain_rows
    FROM retail.invoice_lines l
    WHERE l.source_file_sha256 = p_source_file_sha256
      AND l.policy_version = 'v1'
      AND (
          (l.worksheet = 'Year 2009-2010'
           AND l.invoice_datetime_raw >= timestamp '2010-12-10 00:00:00')
          OR
          (l.worksheet = 'Year 2010-2011'
           AND l.invoice_datetime_raw < timestamp '2010-12-01 00:00:00')
      );
    IF outside_domain_rows <> 0 THEN
        RAISE EXCEPTION 'Annual worksheet contains % out-of-domain line(s)',
            outside_domain_rows;
    END IF;
END
$function$;

CREATE OR REPLACE FUNCTION retail.canonical_period_line_keys_v1(
    p_source_file_sha256 text,
    p_start_inclusive timestamp without time zone,
    p_end_exclusive timestamp without time zone
)
RETURNS TABLE (
    source_file_sha256 text,
    worksheet text,
    source_row_number integer,
    policy_version text
)
LANGUAGE plpgsql
STABLE
AS $function$
BEGIN
    IF p_source_file_sha256 IS NULL OR p_start_inclusive IS NULL
       OR p_end_exclusive IS NULL OR p_start_inclusive >= p_end_exclusive THEN
        RAISE EXCEPTION 'A snapshot and non-empty [start, end) period are required';
    END IF;
    PERFORM retail.assert_uci_502_sheet_domain_v1(p_source_file_sha256);
    PERFORM retail.assert_uci_502_overlap_v1(p_source_file_sha256);
    RETURN QUERY
    SELECT l.source_file_sha256, l.worksheet, l.source_row_number, l.policy_version
    FROM retail.invoice_lines l
    WHERE l.source_file_sha256 = p_source_file_sha256
      AND l.policy_version = 'v1'
      AND l.invoice_datetime_raw >= p_start_inclusive
      AND l.invoice_datetime_raw < p_end_exclusive
      AND (
          (l.worksheet = 'Year 2009-2010'
           AND l.invoice_datetime_raw < timestamp '2010-12-01 00:00:00')
          OR
          (l.worksheet = 'Year 2010-2011'
           AND l.invoice_datetime_raw >= timestamp '2010-12-01 00:00:00')
      );
END
$function$;

INSERT INTO retail.schema_migrations (version, name)
VALUES (7, 'overlap_domain_guard');
