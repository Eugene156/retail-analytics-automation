-- Bounded read-only API role and observed-source-span guard; no cases/actions.
DO $guard$
BEGIN
    IF current_database() <> 'raa_wp2_validation' THEN
        RAISE EXCEPTION 'This bounded deployment requires raa_wp2_validation';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM retail.schema_migrations WHERE version = 11) THEN
        RAISE EXCEPTION 'Migration 011 is required first';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'raa_wp2_api') THEN
        RAISE EXCEPTION 'API role already exists; inspect ownership before proceeding';
    END IF;
END
$guard$;

CREATE ROLE raa_wp2_api NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
    NOREPLICATION NOBYPASSRLS CONNECTION LIMIT 2;
ALTER ROLE raa_wp2_api IN DATABASE raa_wp2_validation
    SET default_transaction_read_only = on;
ALTER ROLE raa_wp2_api IN DATABASE raa_wp2_validation
    SET statement_timeout = '120s';
GRANT CONNECT ON DATABASE raa_wp2_validation TO raa_wp2_api;
GRANT USAGE ON SCHEMA retail TO raa_wp2_api;

CREATE FUNCTION retail.api_comparison_report_v1(
    p_source_file_sha256 text,
    p_start_inclusive timestamp without time zone,
    p_end_exclusive timestamp without time zone,
    p_source_as_of_exclusive timestamp without time zone
)
RETURNS text
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, retail
AS $function$
DECLARE
    first_observed timestamp without time zone;
    last_observed timestamp without time zone;
BEGIN
    IF p_source_file_sha256 IS DISTINCT FROM
        'BCBE73B35F5B7BABF197FB0CB983A11F5D9FF929078D4AA53D171B1F2DF2E980'
       OR p_start_inclusive IS NULL OR p_end_exclusive IS NULL
       OR p_source_as_of_exclusive IS NULL
       OR NOT isfinite(p_start_inclusive) OR NOT isfinite(p_end_exclusive)
       OR NOT isfinite(p_source_as_of_exclusive)
       OR p_start_inclusive >= p_end_exclusive
       OR p_end_exclusive - p_start_inclusive > interval '31 days'
       OR p_source_as_of_exclusive < p_end_exclusive THEN
        RAISE EXCEPTION 'Invalid bounded calculation inputs' USING ERRCODE = '22023';
    END IF;
    SELECT min(l.invoice_datetime_raw), max(l.invoice_datetime_raw)
    INTO first_observed, last_observed
    FROM retail.invoice_lines l
    WHERE l.source_file_sha256 = p_source_file_sha256 AND l.policy_version = 'v1'
      AND ((l.worksheet = 'Year 2009-2010'
            AND l.invoice_datetime_raw < timestamp '2010-12-01')
           OR (l.worksheet = 'Year 2010-2011'
               AND l.invoice_datetime_raw >= timestamp '2010-12-01'));
    -- Conservative observed-row span, not a claim of continuous business coverage.
    -- One microsecond allows the last observed timestamp in a half-open period.
    IF first_observed IS NULL OR last_observed IS NULL
       OR p_start_inclusive - interval '7 days' < first_observed
       OR p_end_exclusive > last_observed + interval '1 microsecond'
       OR p_source_as_of_exclusive > last_observed + interval '1 microsecond' THEN
        RAISE EXCEPTION 'Current or prior period/cutoff is outside observed source span'
            USING ERRCODE = '22023';
    END IF;
    RETURN retail.deterministic_comparison_report_v1(
        p_source_file_sha256, p_start_inclusive, p_end_exclusive,
        p_source_as_of_exclusive)::text;
END
$function$;
REVOKE ALL ON FUNCTION retail.api_comparison_report_v1(text,timestamp,timestamp,timestamp)
    FROM PUBLIC;
GRANT EXECUTE ON FUNCTION retail.api_comparison_report_v1(text,timestamp,timestamp,timestamp)
    TO raa_wp2_api;

INSERT INTO retail.schema_migrations(version, name)
VALUES (12, 'comparison_api_boundary');
