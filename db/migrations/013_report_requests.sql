-- Durable bounded requests; no approval, publication or external side effect.
DO $guard$
BEGIN
    IF current_database() <> 'raa_wp2_validation'
       OR NOT EXISTS (SELECT 1 FROM retail.schema_migrations WHERE version = 12)
       OR EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'raa_wp2_case_api') THEN
        RAISE EXCEPTION 'Migration 012 / isolated database / new role required';
    END IF;
END
$guard$;

CREATE ROLE raa_wp2_case_api NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
    NOREPLICATION NOBYPASSRLS CONNECTION LIMIT 4;
ALTER ROLE raa_wp2_case_api IN DATABASE raa_wp2_validation SET statement_timeout = '120s';
ALTER ROLE raa_wp2_case_api IN DATABASE raa_wp2_validation SET lock_timeout = '5s';
ALTER ROLE raa_wp2_case_api IN DATABASE raa_wp2_validation SET timezone = 'UTC';
GRANT CONNECT ON DATABASE raa_wp2_validation TO raa_wp2_case_api;
GRANT USAGE ON SCHEMA retail TO raa_wp2_case_api;

CREATE TABLE retail.report_cases (
    case_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    requester text NOT NULL DEFAULT 'local-service-v1' CHECK (requester = 'local-service-v1'),
    idempotency_key text NOT NULL CHECK (idempotency_key ~ '^[A-Za-z0-9_-]{8,128}$'),
    request_identity jsonb NOT NULL,
    state text NOT NULL DEFAULT 'received' CHECK (state IN ('received', 'awaiting_approval')),
    current_revision integer,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (requester, idempotency_key),
    CHECK ((state = 'received' AND current_revision IS NULL)
           OR (state = 'awaiting_approval' AND current_revision = 1))
);

CREATE TABLE retail.report_revisions (
    case_id uuid NOT NULL REFERENCES retail.report_cases(case_id),
    revision integer NOT NULL CHECK (revision = 1),
    schema_version text NOT NULL CHECK (schema_version = 'deterministic-comparison-report-v1'),
    payload_text text NOT NULL,
    payload_sha256 text NOT NULL CHECK (
        payload_sha256 = encode(sha256(convert_to(payload_text, 'UTF8')), 'hex')),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (case_id, revision),
    CHECK (payload_text::jsonb ->> 'schema_version' = schema_version)
);
ALTER TABLE retail.report_cases ADD CONSTRAINT report_case_current_revision_fk
    FOREIGN KEY (case_id, current_revision) REFERENCES retail.report_revisions(case_id, revision);

CREATE TABLE retail.report_audit_events (
    event_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    case_id uuid NOT NULL REFERENCES retail.report_cases(case_id),
    event_type text NOT NULL CHECK (event_type IN ('request_received', 'revision_created')),
    revision integer,
    occurred_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    actor text NOT NULL DEFAULT 'local-service-v1' CHECK (actor = 'local-service-v1'),
    UNIQUE (case_id, event_type),
    FOREIGN KEY (case_id, revision) REFERENCES retail.report_revisions(case_id, revision),
    CHECK ((event_type = 'request_received' AND revision IS NULL)
           OR (event_type = 'revision_created' AND revision = 1))
);

CREATE FUNCTION retail.guard_report_case_mutation() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, retail AS $function$
BEGIN
    IF TG_OP <> 'UPDATE' THEN
        RAISE EXCEPTION 'Report cases cannot be deleted or truncated';
    END IF;
    IF NEW.case_id IS DISTINCT FROM OLD.case_id
       OR NEW.requester IS DISTINCT FROM OLD.requester
       OR NEW.idempotency_key IS DISTINCT FROM OLD.idempotency_key
       OR NEW.request_identity IS DISTINCT FROM OLD.request_identity
       OR NEW.created_at IS DISTINCT FROM OLD.created_at
       OR OLD.state <> 'received' OR NEW.state <> 'awaiting_approval'
       OR NEW.current_revision IS DISTINCT FROM 1 THEN
        RAISE EXCEPTION 'Invalid immutable request or lifecycle transition';
    END IF;
    RETURN NEW;
END
$function$;
CREATE TRIGGER report_cases_guard BEFORE UPDATE OR DELETE ON retail.report_cases
    FOR EACH ROW EXECUTE FUNCTION retail.guard_report_case_mutation();
CREATE TRIGGER report_cases_no_truncate BEFORE TRUNCATE ON retail.report_cases
    FOR EACH STATEMENT EXECUTE FUNCTION retail.guard_report_case_mutation();
CREATE TRIGGER report_revisions_immutable BEFORE UPDATE OR DELETE ON retail.report_revisions
    FOR EACH ROW EXECUTE FUNCTION retail.reject_source_mutation();
CREATE TRIGGER report_revisions_no_truncate BEFORE TRUNCATE ON retail.report_revisions
    FOR EACH STATEMENT EXECUTE FUNCTION retail.reject_source_mutation();
CREATE TRIGGER report_audit_immutable BEFORE UPDATE OR DELETE ON retail.report_audit_events
    FOR EACH ROW EXECUTE FUNCTION retail.reject_source_mutation();
CREATE TRIGGER report_audit_no_truncate BEFORE TRUNCATE ON retail.report_audit_events
    FOR EACH STATEMENT EXECUTE FUNCTION retail.reject_source_mutation();

-- Called only by definer functions, never granted to the service role.
CREATE FUNCTION retail.report_case_metadata_v1(p_case_id uuid) RETURNS text
LANGUAGE sql STABLE SET search_path = pg_catalog, retail SET timezone = 'UTC'
AS $function$
    SELECT jsonb_build_object(
        'case_id', c.case_id, 'state', c.state, 'revision', c.current_revision,
        'request', c.request_identity, 'created_at', c.created_at, 'updated_at', c.updated_at,
        'payload_sha256', r.payload_sha256, 'schema_version', r.schema_version,
        'approved', false, 'published', false,
        'audit_events', (SELECT jsonb_agg(jsonb_build_object(
            'event_id', a.event_id, 'event_type', a.event_type, 'revision', a.revision,
            'occurred_at', a.occurred_at, 'actor', a.actor) ORDER BY a.occurred_at, a.event_type)
            FROM retail.report_audit_events a WHERE a.case_id = c.case_id))::text
    FROM retail.report_cases c LEFT JOIN retail.report_revisions r
      ON (r.case_id, r.revision) = (c.case_id, c.current_revision)
    WHERE c.case_id = p_case_id AND c.requester = 'local-service-v1';
$function$;
REVOKE ALL ON FUNCTION retail.report_case_metadata_v1(uuid) FROM PUBLIC;

CREATE FUNCTION retail.api_reserve_report_v1(p_key text, p_hash text,
    p_start timestamp, p_end timestamp, p_asof timestamp) RETURNS text
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, retail
AS $function$
DECLARE
    identity_json jsonb;
    saved retail.report_cases%ROWTYPE;
BEGIN
    IF p_key IS NULL OR p_key !~ '^[A-Za-z0-9_-]{8,128}$'
       OR p_hash IS DISTINCT FROM 'BCBE73B35F5B7BABF197FB0CB983A11F5D9FF929078D4AA53D171B1F2DF2E980'
       OR p_start IS NULL OR p_end IS NULL OR p_asof IS NULL
       OR NOT isfinite(p_start) OR NOT isfinite(p_end) OR NOT isfinite(p_asof)
       OR p_start >= p_end OR p_end - p_start > interval '31 days' OR p_end > p_asof
       -- Bounds measured for this pinned snapshot in migration 012 evidence.
       OR p_start - interval '7 days' < timestamp '2009-12-01 07:45:00'
       OR p_end > timestamp '2011-12-09 12:50:00.000001'
       OR p_asof > timestamp '2011-12-09 12:50:00.000001' THEN
        RAISE EXCEPTION 'Invalid report request' USING ERRCODE = '22023';
    END IF;
    identity_json := jsonb_build_object('contract_version', 'report-request-v1',
        'source_file_sha256', p_hash, 'policy_version', 'v1',
        'report_schema_version', 'deterministic-comparison-report-v1',
        'source_time_interpretation', 'Europe/London-assumed',
        'period_start_inclusive', to_char(p_start, 'YYYY-MM-DD"T"HH24:MI:SS.US'),
        'period_end_exclusive', to_char(p_end, 'YYYY-MM-DD"T"HH24:MI:SS.US'),
        'source_as_of_exclusive', to_char(p_asof, 'YYYY-MM-DD"T"HH24:MI:SS.US'));
    INSERT INTO retail.report_cases(idempotency_key, request_identity)
        VALUES (p_key, identity_json) ON CONFLICT (requester, idempotency_key) DO NOTHING
        RETURNING * INTO saved;
    IF saved.case_id IS NULL THEN
        SELECT * INTO STRICT saved FROM retail.report_cases
            WHERE requester = 'local-service-v1' AND idempotency_key = p_key;
        IF saved.request_identity IS DISTINCT FROM identity_json THEN
            RAISE EXCEPTION 'Idempotency conflict' USING ERRCODE = '23505';
        END IF;
    ELSE
        INSERT INTO retail.report_audit_events(case_id, event_type)
            VALUES (saved.case_id, 'request_received');
    END IF;
    RETURN retail.report_case_metadata_v1(saved.case_id);
END
$function$;

CREATE FUNCTION retail.api_finish_report_v1(p_case_id uuid) RETURNS text
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, retail
AS $function$
DECLARE
    saved retail.report_cases%ROWTYPE;
    report_text text;
BEGIN
    SELECT * INTO saved FROM retail.report_cases
        WHERE case_id = p_case_id AND requester = 'local-service-v1' FOR UPDATE NOWAIT;
    IF NOT FOUND THEN RETURN NULL; END IF;
    IF saved.state = 'awaiting_approval' THEN
        RETURN retail.report_case_metadata_v1(saved.case_id);
    END IF;
    report_text := retail.api_comparison_report_v1(
        saved.request_identity ->> 'source_file_sha256',
        (saved.request_identity ->> 'period_start_inclusive')::timestamp,
        (saved.request_identity ->> 'period_end_exclusive')::timestamp,
        (saved.request_identity ->> 'source_as_of_exclusive')::timestamp);
    INSERT INTO retail.report_revisions(case_id, revision, schema_version, payload_text, payload_sha256)
        VALUES (saved.case_id, 1, 'deterministic-comparison-report-v1', report_text,
                encode(sha256(convert_to(report_text, 'UTF8')), 'hex'));
    UPDATE retail.report_cases SET state = 'awaiting_approval', current_revision = 1,
        updated_at = clock_timestamp() WHERE case_id = saved.case_id;
    INSERT INTO retail.report_audit_events(case_id, event_type, revision)
        VALUES (saved.case_id, 'revision_created', 1);
    RETURN retail.report_case_metadata_v1(saved.case_id);
END
$function$;

CREATE FUNCTION retail.api_get_case_v1(p_case_id uuid) RETURNS text
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, retail
AS $function$ SELECT retail.report_case_metadata_v1(p_case_id); $function$;

CREATE FUNCTION retail.api_get_revision_v1(p_case_id uuid, p_revision integer) RETURNS text
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, retail
AS $function$
    SELECT r.payload_text FROM retail.report_revisions r
      JOIN retail.report_cases c ON c.case_id = r.case_id
    WHERE r.case_id = p_case_id AND r.revision = p_revision
      AND c.requester = 'local-service-v1' AND c.state = 'awaiting_approval';
$function$;

REVOKE ALL ON FUNCTION retail.api_reserve_report_v1(text,text,timestamp,timestamp,timestamp),
    retail.api_finish_report_v1(uuid), retail.api_get_case_v1(uuid),
    retail.api_get_revision_v1(uuid,integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION retail.api_reserve_report_v1(text,text,timestamp,timestamp,timestamp),
    retail.api_finish_report_v1(uuid), retail.api_get_case_v1(uuid),
    retail.api_get_revision_v1(uuid,integer) TO raa_wp2_case_api;

INSERT INTO retail.schema_migrations(version, name) VALUES (13, 'report_requests');
