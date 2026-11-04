-- Additive v2 issuance. Preserve every v1 byte; no decisions or dispatch.
DO $guard$ BEGIN
    IF current_database() <> 'raa_wp2_validation'
       OR NOT EXISTS(SELECT 1 FROM retail.schema_migrations WHERE version=16)
       OR EXISTS(SELECT 1 FROM retail.schema_migrations WHERE version=17) THEN
        RAISE EXCEPTION 'Isolated database / migration 016 / unapplied 017 required';
    END IF;
END $guard$;

CREATE FUNCTION retail.approval_request_payload_v2(
    p_id uuid, p_case uuid, p_revision integer, p_hash text, p_bytes integer,
    p_reviewer uuid, p_created timestamptz, p_expires timestamptz,
    p_generation integer, p_key text, p_predecessor uuid, p_predecessor_hash text
) RETURNS text LANGUAGE sql STABLE SET search_path=pg_catalog,retail SET timezone='UTC' AS $function$
    SELECT (retail.approval_proposal_payload_v1(p_id,p_case,p_revision,p_hash,p_bytes,
        p_reviewer,p_created,p_expires)::jsonb || jsonb_build_object(
        'contract_version','local-approval-proposal-v2','generation',p_generation,
        'request_key',p_key,'predecessor_proposal_id',p_predecessor,
        'predecessor_proposal_sha256',p_predecessor_hash))::text;
$function$;
REVOKE ALL ON FUNCTION retail.approval_request_payload_v2(uuid,uuid,integer,text,integer,uuid,
    timestamptz,timestamptz,integer,text,uuid,text) FROM PUBLIC;

CREATE TABLE retail.approval_requests_v2 (
    proposal_id uuid PRIMARY KEY,
    case_id uuid NOT NULL,
    report_revision integer NOT NULL CHECK(report_revision=1),
    generation integer NOT NULL CHECK(generation>0),
    request_key text NOT NULL CHECK(request_key COLLATE "C" ~ '^[A-Za-z0-9_-]{8,128}$'),
    predecessor_proposal_id uuid UNIQUE REFERENCES retail.approval_requests_v2(proposal_id),
    predecessor_proposal_sha256 text CHECK(predecessor_proposal_sha256 ~ '^[a-f0-9]{64}$'),
    review_policy_version text NOT NULL REFERENCES retail.approval_policies(policy_version),
    reviewer_id uuid NOT NULL,
    report_payload_sha256 text NOT NULL CHECK(report_payload_sha256 ~ '^[a-f0-9]{64}$'),
    content_bytes integer NOT NULL CHECK(content_bytes BETWEEN 1 AND 131072),
    created_at timestamptz NOT NULL,
    expires_at timestamptz NOT NULL,
    payload_text text NOT NULL CHECK(octet_length(payload_text)<=32768 AND payload_text=payload_text::jsonb::text),
    payload_sha256 text NOT NULL CHECK(payload_sha256=encode(sha256(convert_to(payload_text,'UTF8')),'hex')),
    FOREIGN KEY(case_id,report_revision) REFERENCES retail.report_revisions(case_id,revision),
    UNIQUE(case_id,request_key), UNIQUE(case_id,report_revision,generation),
    CHECK(isfinite(created_at) AND isfinite(expires_at) AND expires_at>created_at),
    CHECK((generation=1 AND predecessor_proposal_id IS NULL AND predecessor_proposal_sha256 IS NULL)
        OR (generation>1 AND predecessor_proposal_id IS NOT NULL AND predecessor_proposal_sha256 IS NOT NULL))
);

CREATE FUNCTION retail.guard_approval_request_v2() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,retail SET timezone='UTC' AS $function$
DECLARE policy retail.approval_policies%ROWTYPE; report retail.report_revisions%ROWTYPE;
    saved retail.report_cases%ROWTYPE; previous retail.approval_requests_v2%ROWTYPE; latest integer;
BEGIN
    SELECT * INTO saved FROM retail.report_cases WHERE case_id=NEW.case_id FOR UPDATE NOWAIT;
    IF NOT FOUND OR saved.requester<>'local-service-v1' OR saved.state<>'awaiting_approval'
       OR saved.current_revision IS DISTINCT FROM NEW.report_revision THEN
        RAISE EXCEPTION 'Current unapproved report required';
    END IF;
    SELECT p.* INTO policy FROM retail.approval_policies p JOIN retail.owner_credentials c
        ON c.reviewer_id=p.reviewer_id AND c.revoked_at IS NULL
        WHERE p.policy_version='local-publication-v1' AND p.ttl_seconds=86400;
    IF NOT FOUND OR NEW.review_policy_version IS DISTINCT FROM policy.policy_version
       OR NEW.reviewer_id IS DISTINCT FROM policy.reviewer_id THEN RAISE EXCEPTION 'Owner policy unavailable'; END IF;
    SELECT * INTO report FROM retail.report_revisions WHERE case_id=NEW.case_id AND revision=NEW.report_revision;
    IF NOT FOUND OR report.schema_version<>'deterministic-comparison-report-v1'
       OR NEW.report_payload_sha256 IS DISTINCT FROM report.payload_sha256
       OR report.payload_sha256 IS DISTINCT FROM encode(sha256(convert_to(report.payload_text,'UTF8')),'hex')
       OR NEW.content_bytes IS DISTINCT FROM octet_length(convert_to(report.payload_text,'UTF8')) THEN
        RAISE EXCEPTION 'Report binding failed';
    END IF;
    IF EXISTS(SELECT 1 FROM retail.approval_proposals WHERE case_id=NEW.case_id) THEN
        RAISE EXCEPTION 'Explicit legacy transition required';
    END IF;
    SELECT max(generation) INTO latest FROM retail.approval_requests_v2 WHERE case_id=NEW.case_id;
    IF NEW.generation IS DISTINCT FROM coalesce(latest,0)+1 THEN RAISE EXCEPTION 'Request generation conflict'; END IF;
    IF NEW.generation>1 THEN
        SELECT * INTO previous FROM retail.approval_requests_v2 WHERE proposal_id=NEW.predecessor_proposal_id;
        IF NOT FOUND OR previous.case_id IS DISTINCT FROM NEW.case_id
           OR previous.report_revision IS DISTINCT FROM NEW.report_revision
           OR previous.generation IS DISTINCT FROM latest
           OR previous.payload_sha256 IS DISTINCT FROM NEW.predecessor_proposal_sha256
           OR previous.expires_at>NEW.created_at THEN RAISE EXCEPTION 'Expired latest predecessor required'; END IF;
    END IF;
    IF NEW.created_at<timestamptz '2000-01-01 00:00:00+00' OR NEW.created_at>clock_timestamp()
       OR NEW.expires_at IS DISTINCT FROM NEW.created_at+make_interval(secs=>86400)
       OR NEW.payload_text IS DISTINCT FROM retail.approval_request_payload_v2(
        NEW.proposal_id,NEW.case_id,NEW.report_revision,NEW.report_payload_sha256,NEW.content_bytes,
        NEW.reviewer_id,NEW.created_at,NEW.expires_at,NEW.generation,NEW.request_key,
        NEW.predecessor_proposal_id,NEW.predecessor_proposal_sha256) THEN RAISE EXCEPTION 'Request payload binding failed'; END IF;
    RETURN NEW;
END $function$;
REVOKE ALL ON FUNCTION retail.guard_approval_request_v2() FROM PUBLIC;
CREATE TRIGGER approval_request_guard BEFORE INSERT ON retail.approval_requests_v2
    FOR EACH ROW EXECUTE FUNCTION retail.guard_approval_request_v2();
CREATE TRIGGER approval_request_immutable BEFORE UPDATE OR DELETE ON retail.approval_requests_v2
    FOR EACH ROW EXECUTE FUNCTION retail.reject_source_mutation();
CREATE TRIGGER approval_request_no_truncate BEFORE TRUNCATE ON retail.approval_requests_v2
    FOR EACH STATEMENT EXECUTE FUNCTION retail.reject_source_mutation();

CREATE TABLE retail.approval_request_events_v2 (
    event_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    proposal_id uuid NOT NULL UNIQUE REFERENCES retail.approval_requests_v2(proposal_id),
    event_type text NOT NULL DEFAULT 'approval_request_created' CHECK(event_type='approval_request_created'),
    occurred_at timestamptz NOT NULL CHECK(isfinite(occurred_at)),
    actor text NOT NULL DEFAULT 'local-service-v1' CHECK(actor='local-service-v1')
);
CREATE TRIGGER approval_request_event_immutable BEFORE UPDATE OR DELETE ON retail.approval_request_events_v2
    FOR EACH ROW EXECUTE FUNCTION retail.reject_source_mutation();
CREATE TRIGGER approval_request_event_no_truncate BEFORE TRUNCATE ON retail.approval_request_events_v2
    FOR EACH STATEMENT EXECUTE FUNCTION retail.reject_source_mutation();
REVOKE ALL ON TABLE retail.approval_requests_v2,retail.approval_request_events_v2 FROM PUBLIC;

CREATE FUNCTION retail.api_get_approval_request_v2(p_case uuid,p_id uuid) RETURNS text
LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,retail SET timezone='UTC' AS $function$
    SELECT jsonb_build_object('proposal',r.payload_text::jsonb,'canonical_payload_text',r.payload_text,
        'proposal_sha256',r.payload_sha256,
        'review_status',CASE WHEN statement_timestamp()>=r.expires_at THEN 'expired' ELSE 'pending_review' END,
        'is_current',NOT EXISTS(SELECT 1 FROM retail.approval_requests_v2 n WHERE n.predecessor_proposal_id=r.proposal_id),
        'decision_enabled',false,'approved',false,'published',false,
        'creation_event',jsonb_build_object('event_id',e.event_id,'event_type',e.event_type,
            'occurred_at',e.occurred_at,'actor',e.actor))::text
    FROM retail.approval_requests_v2 r JOIN retail.approval_request_events_v2 e USING(proposal_id)
    JOIN retail.report_cases c ON c.case_id=r.case_id AND c.requester='local-service-v1'
        AND c.state='awaiting_approval' AND c.current_revision=r.report_revision
    WHERE r.case_id=p_case AND r.proposal_id=p_id;
$function$;

CREATE FUNCTION retail.api_current_approval_request_v2(p_case uuid) RETURNS text
LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,retail AS $function$
    SELECT retail.api_get_approval_request_v2(p_case,proposal_id) FROM retail.approval_requests_v2
        WHERE case_id=p_case ORDER BY generation DESC LIMIT 1;
$function$;

CREATE FUNCTION retail.api_issue_approval_request_v2(
    p_case uuid,p_revision integer,p_hash text,p_key text,p_predecessor uuid
) RETURNS text LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,retail SET timezone='UTC' AS $function$
DECLARE policy retail.approval_policies%ROWTYPE; saved retail.report_cases%ROWTYPE;
    report retail.report_revisions%ROWTYPE; existing retail.approval_requests_v2%ROWTYPE;
    previous retail.approval_requests_v2%ROWTYPE; identifier uuid; created timestamptz; expires timestamptz;
    generation integer; body text; content_size integer;
BEGIN
    IF p_case IS NULL OR p_revision IS DISTINCT FROM 1 OR p_hash IS NULL OR p_hash !~ '^[a-f0-9]{64}$'
       OR p_key IS NULL OR p_key COLLATE "C" !~ '^[A-Za-z0-9_-]{8,128}$' THEN
        RAISE EXCEPTION 'Invalid request' USING ERRCODE='22023';
    END IF;
    SELECT p.* INTO policy FROM retail.approval_policies p JOIN retail.owner_credentials c
        ON c.reviewer_id=p.reviewer_id AND c.revoked_at IS NULL
        WHERE p.policy_version='local-publication-v1' AND p.ttl_seconds=86400;
    IF NOT FOUND THEN RAISE EXCEPTION 'Owner policy unavailable' USING ERRCODE='55000'; END IF;
    SELECT * INTO saved FROM retail.report_cases WHERE case_id=p_case AND requester='local-service-v1' FOR UPDATE NOWAIT;
    IF NOT FOUND THEN RETURN NULL; END IF;
    IF saved.state<>'awaiting_approval' OR saved.current_revision IS DISTINCT FROM p_revision THEN
        RAISE EXCEPTION 'Current unapproved report required';
    END IF;
    SELECT * INTO STRICT report FROM retail.report_revisions WHERE case_id=p_case AND revision=p_revision;
    IF report.payload_sha256 IS DISTINCT FROM p_hash THEN RAISE EXCEPTION 'Report hash conflict'; END IF;
    SELECT * INTO existing FROM retail.approval_requests_v2 WHERE case_id=p_case AND request_key=p_key;
    IF FOUND THEN
        IF existing.report_revision IS DISTINCT FROM p_revision OR existing.report_payload_sha256 IS DISTINCT FROM p_hash
           OR existing.predecessor_proposal_id IS DISTINCT FROM p_predecessor THEN RAISE EXCEPTION 'Request key conflict'; END IF;
        RETURN retail.api_get_approval_request_v2(p_case,existing.proposal_id);
    END IF;
    IF EXISTS(SELECT 1 FROM retail.approval_proposals WHERE case_id=p_case) THEN RAISE EXCEPTION 'Explicit legacy transition required'; END IF;
    SELECT * INTO previous FROM retail.approval_requests_v2 WHERE case_id=p_case ORDER BY generation DESC LIMIT 1;
    created:=clock_timestamp();
    IF FOUND THEN
        IF p_predecessor IS DISTINCT FROM previous.proposal_id OR created<previous.expires_at
           OR previous.generation=2147483647 THEN RAISE EXCEPTION 'Expired latest predecessor required'; END IF;
        generation:=previous.generation+1;
    ELSE
        IF p_predecessor IS NOT NULL THEN RAISE EXCEPTION 'Unexpected predecessor'; END IF;
        generation:=1;
    END IF;
    identifier:=gen_random_uuid(); expires:=created+make_interval(secs=>86400);
    content_size:=octet_length(convert_to(report.payload_text,'UTF8'));
    body:=retail.approval_request_payload_v2(identifier,p_case,p_revision,p_hash,content_size,
        policy.reviewer_id,created,expires,generation,p_key,p_predecessor,previous.payload_sha256);
    INSERT INTO retail.approval_requests_v2 VALUES(identifier,p_case,p_revision,generation,p_key,p_predecessor,
        previous.payload_sha256,policy.policy_version,policy.reviewer_id,p_hash,content_size,created,expires,
        body,encode(sha256(convert_to(body,'UTF8')),'hex'));
    INSERT INTO retail.approval_request_events_v2(proposal_id,occurred_at) VALUES(identifier,created);
    RETURN retail.api_get_approval_request_v2(p_case,identifier);
END $function$;

CREATE FUNCTION retail.api_owner_approval_request_v2(p_digest text,p_case uuid,p_id uuid) RETURNS text
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,retail AS $function$
DECLARE identity uuid; result text;
BEGIN
    identity:=retail.api_owner_identity_v1(p_digest);
    IF identity IS NULL THEN RAISE EXCEPTION 'Unauthorized' USING ERRCODE='42501'; END IF;
    result:=retail.api_get_approval_request_v2(p_case,p_id);
    IF result IS NOT NULL AND (result::jsonb #>> '{proposal,reviewer_id}')::uuid IS DISTINCT FROM identity THEN
        RAISE EXCEPTION 'Unauthorized' USING ERRCODE='42501';
    END IF;
    RETURN result;
END $function$;

CREATE FUNCTION retail.api_owner_current_request_v2(p_digest text,p_case uuid) RETURNS text
LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,retail AS $function$
    -- Always authenticate even when no request exists.
    SELECT retail.api_owner_approval_request_v2(p_digest,p_case,
        (SELECT proposal_id FROM retail.approval_requests_v2 WHERE case_id=p_case ORDER BY generation DESC LIMIT 1));
$function$;

REVOKE ALL ON FUNCTION retail.api_get_approval_request_v2(uuid,uuid),retail.api_current_approval_request_v2(uuid),
    retail.api_issue_approval_request_v2(uuid,integer,text,text,uuid),
    retail.api_owner_approval_request_v2(text,uuid,uuid),retail.api_owner_current_request_v2(text,uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION retail.api_get_approval_request_v2(uuid,uuid),retail.api_current_approval_request_v2(uuid),
    retail.api_issue_approval_request_v2(uuid,integer,text,text,uuid) TO raa_wp2_case_api;
GRANT EXECUTE ON FUNCTION retail.api_owner_approval_request_v2(text,uuid,uuid),
    retail.api_owner_current_request_v2(text,uuid) TO raa_wp4_reviewer_api;
-- V1 getters and bytes remain intact; old runtime issuance cannot race v2.
REVOKE EXECUTE ON FUNCTION retail.api_prepare_approval_proposal_v1(uuid,integer,text) FROM raa_wp2_case_api;
INSERT INTO retail.schema_migrations(version,name) VALUES(17,'explicit_approval_requests');
