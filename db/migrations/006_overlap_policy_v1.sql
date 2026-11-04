-- WP2 migration 006. Analytical worksheet ownership for UCI Online Retail II.
-- Source rows are never deduplicated, updated or deleted. Reconcile the complete
-- imported sheets before selecting one sheet on either side of the cutover.
DO $guard$
BEGIN
    IF current_database() = 'n8n' THEN
        RAISE EXCEPTION 'Refusing to install business functions in n8n metadata DB';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM retail.schema_migrations WHERE version = 5) THEN
        RAISE EXCEPTION 'Migration 005 is required first';
    END IF;
END
$guard$;

CREATE FUNCTION retail.assert_uci_502_overlap_v1(p_source_file_sha256 text)
RETURNS void
LANGUAGE plpgsql
STABLE
AS $function$
DECLARE
    sheet_name text;
    expected_rows bigint;
    raw_count bigint;
    line_count bigint;
    undated_count bigint;
    older_overlap bigint;
    newer_overlap bigint;
    differing_groups bigint;
BEGIN
    IF p_source_file_sha256 IS NULL THEN
        RAISE EXCEPTION 'A source snapshot is required';
    END IF;
    FOREACH sheet_name IN ARRAY ARRAY['Year 2009-2010', 'Year 2010-2011'] LOOP
        SELECT s.expected_data_rows INTO expected_rows
        FROM retail.source_sheets s
        WHERE s.source_file_sha256 = p_source_file_sha256
          AND s.worksheet = sheet_name;
        IF expected_rows IS NULL THEN
            RAISE EXCEPTION 'Required annual worksheet is not registered';
        END IF;
        SELECT count(*) INTO raw_count
        FROM retail.source_rows r
        WHERE r.source_file_sha256 = p_source_file_sha256
          AND r.worksheet = sheet_name;
        SELECT count(*), count(*) FILTER (WHERE l.invoice_datetime_raw IS NULL)
        INTO line_count, undated_count
        FROM retail.invoice_lines l
        WHERE l.source_file_sha256 = p_source_file_sha256
          AND l.worksheet = sheet_name
          AND l.policy_version = 'v1';
        IF raw_count <> expected_rows OR line_count <> expected_rows
           OR undated_count <> 0 THEN
            RAISE EXCEPTION 'Annual worksheet is incomplete or contains undated lines';
        END IF;
    END LOOP;

    WITH grouped AS (
        SELECT l.invoice_datetime_raw::date AS source_day, r.raw_cells,
               count(*) FILTER (WHERE r.worksheet = 'Year 2009-2010') AS older_n,
               count(*) FILTER (WHERE r.worksheet = 'Year 2010-2011') AS newer_n
        FROM retail.source_rows r
        JOIN retail.invoice_lines l USING
            (source_file_sha256, worksheet, source_row_number)
        WHERE r.source_file_sha256 = p_source_file_sha256
          AND l.policy_version = 'v1'
          AND l.invoice_datetime_raw >= timestamp '2010-12-01 00:00:00'
          AND l.invoice_datetime_raw < timestamp '2010-12-10 00:00:00'
          AND r.worksheet IN ('Year 2009-2010', 'Year 2010-2011')
        GROUP BY l.invoice_datetime_raw::date, r.raw_cells
    )
    SELECT coalesce(sum(g.older_n), 0), coalesce(sum(g.newer_n), 0),
           count(*) FILTER (WHERE g.older_n <> g.newer_n)
    INTO older_overlap, newer_overlap, differing_groups
    FROM grouped g;
    IF older_overlap = 0 OR newer_overlap = 0 OR differing_groups <> 0 THEN
        RAISE EXCEPTION 'Annual worksheet overlap differs: % conflicting value group(s)',
            differing_groups;
    END IF;
END
$function$;

CREATE FUNCTION retail.canonical_period_line_keys_v1(
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
VALUES (6, 'uci_502_overlap_policy_v1');
