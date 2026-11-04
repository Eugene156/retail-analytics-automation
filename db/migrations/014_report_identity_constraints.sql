-- Close SQL CHECK/NULL loopholes independently of the fixed API functions.
DO $guard$
BEGIN
    IF current_database() <> 'raa_wp2_validation'
       OR NOT EXISTS (SELECT 1 FROM retail.schema_migrations WHERE version = 13) THEN
        RAISE EXCEPTION 'Migration 013 / isolated database required';
    END IF;
END
$guard$;
ALTER TABLE retail.report_cases ADD CONSTRAINT report_request_contract_required CHECK (
    (jsonb_typeof(request_identity) = 'object'
     AND request_identity ->> 'contract_version' = 'report-request-v1'
     AND request_identity ->> 'source_file_sha256' =
         'BCBE73B35F5B7BABF197FB0CB983A11F5D9FF929078D4AA53D171B1F2DF2E980'
     AND request_identity ->> 'policy_version' = 'v1'
     AND request_identity ->> 'report_schema_version' = 'deterministic-comparison-report-v1'
     AND request_identity ->> 'source_time_interpretation' = 'Europe/London-assumed'
     AND request_identity ?& ARRAY['period_start_inclusive', 'period_end_exclusive', 'source_as_of_exclusive']) IS TRUE
);
ALTER TABLE retail.report_revisions ADD CONSTRAINT report_payload_schema_required CHECK (
    jsonb_typeof(payload_text::jsonb) = 'object'
    AND (payload_text::jsonb ->> 'schema_version') IS NOT DISTINCT FROM schema_version
);
INSERT INTO retail.schema_migrations(version, name) VALUES (14, 'report_identity_constraints');
