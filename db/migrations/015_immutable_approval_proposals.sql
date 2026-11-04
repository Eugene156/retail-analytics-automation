-- WP4: prepare immutable local proposals only. No decisions/outbox/publication.
DO $guard$
BEGIN
    IF current_database() <> 'raa_wp2_validation'
       OR NOT EXISTS (SELECT 1 FROM retail.schema_migrations WHERE version = 14)
       OR EXISTS (SELECT 1 FROM retail.schema_migrations WHERE version = 15) THEN
        RAISE EXCEPTION 'Isolated database / migration 014 / unapplied 015 required';
    END IF;
END
$guard$;

-- Intentionally empty. A future owner-authorized identity bootstrap must bind
-- this UUID to an authenticated human; a service caller cannot supply it.
CREATE TABLE retail.approval_policies (
    policy_version text PRIMARY KEY CHECK (policy_version = 'local-publication-v1'),
    reviewer_id uuid NOT NULL CHECK (reviewer_id <> '00000000-0000-0000-0000-000000000000'),
    ttl_seconds integer NOT NULL CHECK (ttl_seconds BETWEEN 60 AND 86400)
);
CREATE TRIGGER approval_policies_immutable BEFORE UPDATE OR DELETE ON retail.approval_policies
    FOR EACH ROW EXECUTE FUNCTION retail.reject_source_mutation();
CREATE TRIGGER approval_policies_no_truncate BEFORE TRUNCATE ON retail.approval_policies
    FOR EACH STATEMENT EXECUTE FUNCTION retail.reject_source_mutation();

CREATE FUNCTION retail.approval_proposal_payload_v1(
    p_proposal_id uuid, p_case_id uuid, p_revision integer, p_report_hash text,
    p_content_bytes integer, p_reviewer_id uuid, p_created timestamptz, p_expires timestamptz
) RETURNS text LANGUAGE sql STABLE STRICT
SET search_path = pg_catalog, retail SET timezone = 'UTC' AS $function$
    SELECT jsonb_build_object(
        'contract_version', 'local-approval-proposal-v1',
        'canonicalization', 'postgresql-jsonb-text-v1',
        'proposal_id', p_proposal_id, 'case_id', p_case_id, 'report_revision', p_revision,
        'report_payload_sha256', p_report_hash,
        'report_schema_version', 'deterministic-comparison-report-v1',
        'source_file_sha256', 'BCBE73B35F5B7BABF197FB0CB983A11F5D9FF929078D4AA53D171B1F2DF2E980',
        'report_policy_version', 'v1', 'review_policy_version', 'local-publication-v1',
        'reviewer_id', p_reviewer_id,
        'created_at', to_char(p_created AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
        'expires_at', to_char(p_expires AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
        'action', jsonb_build_object(
            'type', 'publish_local_report_json_v1', 'content_sha256', p_report_hash,
            'content_bytes', p_content_bytes,
            'target', jsonb_build_object(
                'target_id', 'local-approved-report-json-v1',
                'relative_path', 'reports/approved/v1/' || p_case_id::text || '/revision-1.json',
                'media_type', 'application/json'))
    )::text;
$function$;
REVOKE ALL ON FUNCTION retail.approval_proposal_payload_v1(uuid,uuid,integer,text,integer,uuid,timestamptz,timestamptz) FROM PUBLIC;

CREATE TABLE retail.approval_proposals (
    proposal_id uuid PRIMARY KEY,
    case_id uuid NOT NULL,
    report_revision integer NOT NULL CHECK (report_revision = 1),
    review_policy_version text NOT NULL REFERENCES retail.approval_policies(policy_version),
    reviewer_id uuid NOT NULL,
    report_payload_sha256 text NOT NULL CHECK (report_payload_sha256 ~ '^[a-f0-9]{64}$'),
    content_bytes integer NOT NULL CHECK (content_bytes BETWEEN 1 AND 131072),
    created_at timestamptz NOT NULL,
    expires_at timestamptz NOT NULL,
    payload_text text NOT NULL CHECK (octet_length(payload_text) <= 32768
        AND payload_text = payload_text::jsonb::text),
    payload_sha256 text NOT NULL CHECK (
        payload_sha256 = encode(sha256(convert_to(payload_text, 'UTF8')), 'hex')),
    FOREIGN KEY (case_id, report_revision) REFERENCES retail.report_revisions(case_id, revision),
    UNIQUE (case_id, report_revision),
    CHECK (isfinite(created_at) AND isfinite(expires_at) AND expires_at > created_at)
);

CREATE FUNCTION retail.guard_approval_proposal_insert_v1() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, retail AS $function$
DECLARE
    policy retail.approval_policies%ROWTYPE;
    stored_revision retail.report_revisions%ROWTYPE;
    case_state text;
    current_version integer;
BEGIN
    SELECT * INTO policy FROM retail.approval_policies WHERE policy_version = NEW.review_policy_version;
    IF NOT FOUND OR NEW.reviewer_id IS DISTINCT FROM policy.reviewer_id THEN
        RAISE EXCEPTION 'Unknown proposal reviewer policy';
    END IF;
    SELECT * INTO stored_revision FROM retail.report_revisions
        WHERE case_id = NEW.case_id AND revision = NEW.report_revision;
    IF NOT FOUND OR stored_revision.schema_version <> 'deterministic-comparison-report-v1'
       OR NEW.report_payload_sha256 IS DISTINCT FROM stored_revision.payload_sha256
       OR stored_revision.payload_sha256 IS DISTINCT FROM encode(sha256(convert_to(stored_revision.payload_text, 'UTF8')), 'hex')
       OR NEW.content_bytes IS DISTINCT FROM octet_length(convert_to(stored_revision.payload_text, 'UTF8')) THEN
        RAISE EXCEPTION 'Proposal report identity failed';
    END IF;
    SELECT state, current_revision INTO case_state, current_version FROM retail.report_cases WHERE case_id = NEW.case_id;
    IF case_state IS DISTINCT FROM 'awaiting_approval' OR current_version IS DISTINCT FROM NEW.report_revision
       OR NEW.created_at < timestamptz '2000-01-01 00:00:00+00'
       OR NEW.created_at > clock_timestamp()
       OR NEW.expires_at IS DISTINCT FROM NEW.created_at + make_interval(secs => policy.ttl_seconds)
       OR NEW.payload_text IS DISTINCT FROM retail.approval_proposal_payload_v1(
            NEW.proposal_id, NEW.case_id, NEW.report_revision, NEW.report_payload_sha256,
            NEW.content_bytes, NEW.reviewer_id, NEW.created_at, NEW.expires_at) THEN
        RAISE EXCEPTION 'Proposal binding failed';
    END IF;
    RETURN NEW;
END
$function$;
CREATE TRIGGER approval_proposal_insert_guard BEFORE INSERT ON retail.approval_proposals
    FOR EACH ROW EXECUTE FUNCTION retail.guard_approval_proposal_insert_v1();
CREATE TRIGGER approval_proposals_immutable BEFORE UPDATE OR DELETE ON retail.approval_proposals
    FOR EACH ROW EXECUTE FUNCTION retail.reject_source_mutation();
CREATE TRIGGER approval_proposals_no_truncate BEFORE TRUNCATE ON retail.approval_proposals
    FOR EACH STATEMENT EXECUTE FUNCTION retail.reject_source_mutation();

CREATE TABLE retail.proposal_audit_events (
    event_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    proposal_id uuid NOT NULL UNIQUE REFERENCES retail.approval_proposals(proposal_id),
    event_type text NOT NULL DEFAULT 'proposal_created' CHECK (event_type = 'proposal_created'),
    occurred_at timestamptz NOT NULL CHECK (isfinite(occurred_at)),
    actor text NOT NULL DEFAULT 'local-service-v1' CHECK (actor = 'local-service-v1')
);
CREATE TRIGGER proposal_audit_immutable BEFORE UPDATE OR DELETE ON retail.proposal_audit_events
    FOR EACH ROW EXECUTE FUNCTION retail.reject_source_mutation();
CREATE TRIGGER proposal_audit_no_truncate BEFORE TRUNCATE ON retail.proposal_audit_events
    FOR EACH STATEMENT EXECUTE FUNCTION retail.reject_source_mutation();

CREATE FUNCTION retail.api_get_approval_proposal_v1(p_case_id uuid) RETURNS text
LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path = pg_catalog, retail SET timezone = 'UTC'
AS $function$
    SELECT jsonb_build_object(
        'proposal', p.payload_text::jsonb,
        'canonical_payload_text', p.payload_text, 'proposal_sha256', p.payload_sha256,
        'review_status', CASE WHEN statement_timestamp() >= p.expires_at THEN 'expired' ELSE 'pending_review' END,
        'decision_enabled', false, 'approved', false, 'published', false,
        'creation_event', jsonb_build_object('event_id', a.event_id, 'event_type', a.event_type,
            'occurred_at', a.occurred_at, 'actor', a.actor)
    )::text
    FROM retail.approval_proposals p
    JOIN retail.report_cases c ON c.case_id = p.case_id AND c.requester = 'local-service-v1'
    JOIN retail.proposal_audit_events a ON a.proposal_id = p.proposal_id
    WHERE p.case_id = p_case_id AND c.state = 'awaiting_approval' AND c.current_revision = p.report_revision;
$function$;
REVOKE ALL ON FUNCTION retail.api_get_approval_proposal_v1(uuid) FROM PUBLIC;

CREATE FUNCTION retail.api_prepare_approval_proposal_v1(p_case_id uuid, p_revision integer, p_report_hash text)
RETURNS text LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, retail SET timezone = 'UTC' AS $function$
DECLARE
    policy retail.approval_policies%ROWTYPE;
    saved retail.report_cases%ROWTYPE;
    report retail.report_revisions%ROWTYPE;
    proposal_uuid uuid;
    created timestamptz;
    expires timestamptz;
    content_size integer;
    body text;
BEGIN
    IF p_case_id IS NULL OR p_revision IS DISTINCT FROM 1
       OR p_report_hash IS NULL OR p_report_hash !~ '^[a-f0-9]{64}$' THEN
        RAISE EXCEPTION 'Invalid proposal request' USING ERRCODE = '22023';
    END IF;
    SELECT * INTO policy FROM retail.approval_policies WHERE policy_version = 'local-publication-v1';
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Reviewer policy is not configured' USING ERRCODE = '55000';
    END IF;
    SELECT * INTO saved FROM retail.report_cases WHERE case_id = p_case_id
        AND requester = 'local-service-v1' FOR UPDATE NOWAIT;
    IF NOT FOUND THEN RETURN NULL; END IF;
    IF saved.state <> 'awaiting_approval' OR saved.current_revision IS DISTINCT FROM p_revision THEN
        RAISE EXCEPTION 'A current unapproved report is required';
    END IF;
    SELECT * INTO STRICT report FROM retail.report_revisions WHERE case_id = p_case_id AND revision = p_revision;
    IF report.payload_sha256 IS DISTINCT FROM p_report_hash THEN
        RAISE EXCEPTION 'Report hash differs from the requested revision';
    END IF;
    IF EXISTS (SELECT 1 FROM retail.approval_proposals WHERE case_id = p_case_id AND report_revision = p_revision) THEN
        -- Replay never refreshes expiry or replaces the original binding.
        RETURN retail.api_get_approval_proposal_v1(p_case_id);
    END IF;
    proposal_uuid := gen_random_uuid();
    created := clock_timestamp();
    expires := created + make_interval(secs => policy.ttl_seconds);
    content_size := octet_length(convert_to(report.payload_text, 'UTF8'));
    body := retail.approval_proposal_payload_v1(proposal_uuid, p_case_id, p_revision,
        p_report_hash, content_size, policy.reviewer_id, created, expires);
    INSERT INTO retail.approval_proposals VALUES (proposal_uuid, p_case_id, p_revision,
        policy.policy_version, policy.reviewer_id, p_report_hash, content_size, created, expires,
        body, encode(sha256(convert_to(body, 'UTF8')), 'hex'));
    INSERT INTO retail.proposal_audit_events(proposal_id, occurred_at) VALUES (proposal_uuid, created);
    RETURN retail.api_get_approval_proposal_v1(p_case_id);
END
$function$;
REVOKE ALL ON FUNCTION retail.api_prepare_approval_proposal_v1(uuid,integer,text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION retail.api_get_approval_proposal_v1(uuid),
    retail.api_prepare_approval_proposal_v1(uuid,integer,text) TO raa_wp2_case_api;

INSERT INTO retail.schema_migrations(version, name) VALUES (15, 'immutable_approval_proposals');
