-- Staged SQL contract only. No API grant, login, worker or publication.
DO $guard$ BEGIN
 IF current_database()<>'raa_wp2_validation'
    OR NOT EXISTS(SELECT 1 FROM retail.schema_migrations WHERE version=18)
    OR EXISTS(SELECT 1 FROM pg_roles WHERE rolname='raa_wp4_decision_api') THEN
   RAISE EXCEPTION 'Isolated migration 018 database and new decision role required';
 END IF;
END $guard$;
CREATE ROLE raa_wp4_decision_api NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
 NOREPLICATION NOBYPASSRLS CONNECTION LIMIT 4;
GRANT CONNECT ON DATABASE raa_wp2_validation TO raa_wp4_decision_api;
GRANT USAGE ON SCHEMA retail TO raa_wp4_decision_api;
ALTER ROLE raa_wp4_decision_api IN DATABASE raa_wp2_validation SET statement_timeout='5s';
ALTER ROLE raa_wp4_decision_api IN DATABASE raa_wp2_validation SET lock_timeout='5s';
ALTER ROLE raa_wp4_decision_api IN DATABASE raa_wp2_validation SET default_transaction_read_only=on;

CREATE FUNCTION retail.decision_payload_v1(p_id uuid,p_case uuid,p_proposal uuid,p_revision integer,
 p_proposal_hash text,p_report_hash text,p_reviewer uuid,p_key text,p_outcome text,
 p_decided timestamptz,p_expires timestamptz) RETURNS text
LANGUAGE sql STABLE STRICT SET search_path=pg_catalog,retail SET timezone='UTC' AS $function$
 SELECT jsonb_build_object('contract_version','local-review-decision-v1',
  'canonicalization','postgresql-jsonb-text-v1','decision_id',p_id,'case_id',p_case,
  'proposal_id',p_proposal,'proposal_contract_version','local-approval-proposal-v2',
  'report_revision',p_revision,'proposal_sha256',p_proposal_hash,'report_payload_sha256',p_report_hash,
  'reviewer_id',p_reviewer,'decision_key',p_key,'outcome',p_outcome,
  'decided_at',to_char(p_decided AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
  'authorization_expires_at',to_char(p_expires AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US"Z"'))::text;
$function$;
REVOKE ALL ON FUNCTION retail.decision_payload_v1(uuid,uuid,uuid,integer,text,text,uuid,text,text,timestamptz,timestamptz) FROM PUBLIC;

CREATE TABLE retail.review_decisions_v1 (
 decision_id uuid PRIMARY KEY,
 case_id uuid NOT NULL,
 proposal_id uuid NOT NULL UNIQUE REFERENCES retail.approval_requests_v2(proposal_id),
 report_revision integer NOT NULL CHECK(report_revision=1),
 proposal_sha256 text NOT NULL CHECK(proposal_sha256 ~ '^[a-f0-9]{64}$'),
 report_payload_sha256 text NOT NULL CHECK(report_payload_sha256 ~ '^[a-f0-9]{64}$'),
 reviewer_id uuid NOT NULL REFERENCES retail.owner_credentials(reviewer_id),
 session_sha256 text NOT NULL REFERENCES retail.owner_portal_sessions(session_sha256),
 decision_key text NOT NULL CHECK(decision_key COLLATE "C" ~ '^[A-Za-z0-9_-]{8,128}$'),
 outcome text NOT NULL CHECK(outcome IN ('approved','rejected','expired')),
 decided_at timestamptz NOT NULL CHECK(isfinite(decided_at)),
 authorization_expires_at timestamptz NOT NULL CHECK(isfinite(authorization_expires_at)),
 payload_text text NOT NULL CHECK(octet_length(payload_text)<=32768 AND payload_text=payload_text::jsonb::text),
 payload_sha256 text NOT NULL CHECK(payload_sha256=encode(sha256(convert_to(payload_text,'UTF8')),'hex')),
 FOREIGN KEY(case_id,report_revision) REFERENCES retail.report_revisions(case_id,revision),
 UNIQUE(case_id,decision_key)
);
-- Expiry closes a request, not the case: an explicit successor remains possible.
CREATE UNIQUE INDEX one_terminal_review_v1 ON retail.review_decisions_v1(case_id,report_revision)
 WHERE outcome IN ('approved','rejected');

CREATE TABLE retail.review_decision_events_v1 (
 event_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 decision_id uuid NOT NULL UNIQUE REFERENCES retail.review_decisions_v1(decision_id),
 event_type text NOT NULL CHECK(event_type IN ('review_approved','review_rejected','review_expired')),
 reviewer_id uuid NOT NULL REFERENCES retail.owner_credentials(reviewer_id),
 occurred_at timestamptz NOT NULL CHECK(isfinite(occurred_at))
);
CREATE TABLE retail.publication_outbox_v1 (
 action_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 action_key text NOT NULL UNIQUE,
 decision_id uuid NOT NULL UNIQUE REFERENCES retail.review_decisions_v1(decision_id),
 proposal_id uuid NOT NULL UNIQUE REFERENCES retail.approval_requests_v2(proposal_id),
 case_id uuid NOT NULL,
 report_revision integer NOT NULL CHECK(report_revision=1),
 action_type text NOT NULL CHECK(action_type='publish_local_report_json_v1'),
 target_id text NOT NULL CHECK(target_id='local-approved-report-json-v1'),
 relative_path text NOT NULL,
 content_text text NOT NULL,
 content_sha256 text NOT NULL CHECK(content_sha256=encode(sha256(convert_to(content_text,'UTF8')),'hex')),
 content_bytes integer NOT NULL CHECK(content_bytes=octet_length(convert_to(content_text,'UTF8')) AND content_bytes BETWEEN 1 AND 131072),
 action_payload_text text NOT NULL CHECK(action_payload_text=action_payload_text::jsonb::text),
 action_payload_sha256 text NOT NULL CHECK(action_payload_sha256=encode(sha256(convert_to(action_payload_text,'UTF8')),'hex')),
 proposal_sha256 text NOT NULL CHECK(proposal_sha256 ~ '^[a-f0-9]{64}$'),
 created_at timestamptz NOT NULL CHECK(isfinite(created_at)),
 authorization_expires_at timestamptz NOT NULL CHECK(isfinite(authorization_expires_at)),
 state text NOT NULL DEFAULT 'pending' CHECK(state='pending'),
 FOREIGN KEY(case_id,report_revision) REFERENCES retail.report_revisions(case_id,revision),
 UNIQUE(case_id,report_revision,action_type,target_id)
);
REVOKE ALL ON TABLE retail.review_decisions_v1,retail.review_decision_events_v1,retail.publication_outbox_v1 FROM PUBLIC;

CREATE FUNCTION retail.guard_review_decision_v1() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,retail AS $function$
DECLARE r retail.approval_requests_v2%ROWTYPE; c retail.report_cases%ROWTYPE; s retail.owner_portal_sessions%ROWTYPE;
BEGIN
 SELECT * INTO c FROM retail.report_cases WHERE case_id=NEW.case_id FOR UPDATE NOWAIT;
 SELECT * INTO r FROM retail.approval_requests_v2 WHERE proposal_id=NEW.proposal_id;
 SELECT * INTO s FROM retail.owner_portal_sessions WHERE session_sha256=NEW.session_sha256;
 IF c.case_id IS NULL OR c.requester<>'local-service-v1' OR c.state<>'awaiting_approval'
   OR c.current_revision IS DISTINCT FROM NEW.report_revision OR r.case_id IS DISTINCT FROM NEW.case_id
   OR r.report_revision IS DISTINCT FROM NEW.report_revision OR r.payload_sha256 IS DISTINCT FROM NEW.proposal_sha256
   OR r.report_payload_sha256 IS DISTINCT FROM NEW.report_payload_sha256
   OR r.reviewer_id IS DISTINCT FROM NEW.reviewer_id
   OR r.expires_at IS DISTINCT FROM NEW.authorization_expires_at
   OR (r.payload_text::jsonb->>'contract_version') IS DISTINCT FROM 'local-approval-proposal-v2'
   OR EXISTS(SELECT 1 FROM retail.approval_requests_v2 WHERE predecessor_proposal_id=r.proposal_id)
   OR s.reviewer_id IS DISTINCT FROM NEW.reviewer_id OR s.revoked_at IS NOT NULL
   OR s.created_at>NEW.decided_at OR s.expires_at<=NEW.decided_at
   OR retail.api_portal_identity_v1(NEW.session_sha256) IS DISTINCT FROM NEW.reviewer_id
   OR NEW.decided_at<r.created_at OR NEW.decided_at>clock_timestamp()
   OR (NEW.outcome IN ('approved','rejected') AND NEW.decided_at>=r.expires_at)
   OR (NEW.outcome='expired' AND NEW.decided_at<r.expires_at)
   OR NEW.payload_text IS DISTINCT FROM retail.decision_payload_v1(NEW.decision_id,NEW.case_id,NEW.proposal_id,
     NEW.report_revision,NEW.proposal_sha256,NEW.report_payload_sha256,NEW.reviewer_id,NEW.decision_key,
     NEW.outcome,NEW.decided_at,NEW.authorization_expires_at) THEN
   RAISE EXCEPTION 'Decision binding failed' USING ERRCODE='22023';
 END IF;
 RETURN NEW;
END $function$;
CREATE TRIGGER review_decision_binding BEFORE INSERT ON retail.review_decisions_v1
 FOR EACH ROW EXECUTE FUNCTION retail.guard_review_decision_v1();

CREATE FUNCTION retail.guard_review_event_v1() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,retail AS $function$
DECLARE d retail.review_decisions_v1%ROWTYPE;
BEGIN
 SELECT * INTO d FROM retail.review_decisions_v1 WHERE decision_id=NEW.decision_id;
 IF d.decision_id IS NULL OR NEW.event_type IS DISTINCT FROM 'review_'||d.outcome
   OR NEW.reviewer_id IS DISTINCT FROM d.reviewer_id OR NEW.occurred_at IS DISTINCT FROM d.decided_at THEN
   RAISE EXCEPTION 'Decision event binding failed';
 END IF;
 RETURN NEW;
END $function$;
CREATE TRIGGER review_event_binding BEFORE INSERT ON retail.review_decision_events_v1
 FOR EACH ROW EXECUTE FUNCTION retail.guard_review_event_v1();

CREATE FUNCTION retail.guard_publication_intent_v1() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,retail AS $function$
DECLARE d retail.review_decisions_v1%ROWTYPE; r retail.approval_requests_v2%ROWTYPE; report retail.report_revisions%ROWTYPE;
BEGIN
 SELECT * INTO d FROM retail.review_decisions_v1 WHERE decision_id=NEW.decision_id;
 SELECT * INTO r FROM retail.approval_requests_v2 WHERE proposal_id=d.proposal_id;
 SELECT * INTO report FROM retail.report_revisions WHERE case_id=d.case_id AND revision=d.report_revision;
 IF d.decision_id IS NULL OR d.outcome<>'approved' OR NEW.proposal_id IS DISTINCT FROM d.proposal_id
   OR NEW.case_id IS DISTINCT FROM d.case_id OR NEW.report_revision IS DISTINCT FROM d.report_revision
   OR NEW.action_key IS DISTINCT FROM 'publish-local-v1:'||d.proposal_id::text
   OR NEW.action_type IS DISTINCT FROM 'publish_local_report_json_v1'
   OR NEW.target_id IS DISTINCT FROM 'local-approved-report-json-v1'
   OR NEW.relative_path IS DISTINCT FROM 'reports/approved/v1/'||d.case_id::text||'/revision-1.json'
   OR NEW.content_text IS DISTINCT FROM report.payload_text OR NEW.content_sha256 IS DISTINCT FROM d.report_payload_sha256
   OR NEW.content_bytes IS DISTINCT FROM r.content_bytes
   OR NEW.action_payload_text IS DISTINCT FROM (r.payload_text::jsonb->'action')::text
   OR NEW.proposal_sha256 IS DISTINCT FROM d.proposal_sha256
   OR NEW.created_at IS DISTINCT FROM d.decided_at OR NEW.authorization_expires_at IS DISTINCT FROM r.expires_at THEN
   RAISE EXCEPTION 'Publication intent binding failed';
 END IF;
 RETURN NEW;
END $function$;
CREATE TRIGGER publication_intent_binding BEFORE INSERT ON retail.publication_outbox_v1
 FOR EACH ROW EXECUTE FUNCTION retail.guard_publication_intent_v1();

-- A committed decision cannot omit its event / approved intent. These are
-- deferred until transaction end so the fixed function can insert all three.
CREATE FUNCTION retail.guard_decision_bundle_v1() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,retail AS $function$
BEGIN
 IF NOT EXISTS(SELECT 1 FROM retail.review_decision_events_v1 WHERE decision_id=NEW.decision_id)
   OR (NEW.outcome='approved') IS DISTINCT FROM
      EXISTS(SELECT 1 FROM retail.publication_outbox_v1 WHERE decision_id=NEW.decision_id) THEN
   RAISE EXCEPTION 'Incomplete decision event/outbox bundle';
 END IF;
 RETURN NULL;
END $function$;
CREATE CONSTRAINT TRIGGER review_decision_complete AFTER INSERT ON retail.review_decisions_v1
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION retail.guard_decision_bundle_v1();

CREATE FUNCTION retail.reject_terminal_successor_v1() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,retail AS $function$
BEGIN
 -- Same case lock as issuance/decision, independent of application workers.
 PERFORM 1 FROM retail.report_cases WHERE case_id=NEW.case_id FOR UPDATE NOWAIT;
 IF EXISTS(SELECT 1 FROM retail.review_decisions_v1 WHERE case_id=NEW.case_id
     AND report_revision=NEW.report_revision AND outcome IN ('approved','rejected')) THEN
   RAISE EXCEPTION 'Terminal review cannot be replaced' USING ERRCODE='55000';
 END IF;
 RETURN NEW;
END $function$;
CREATE TRIGGER approval_request_terminal_guard BEFORE INSERT ON retail.approval_requests_v2
 FOR EACH ROW EXECUTE FUNCTION retail.reject_terminal_successor_v1();

CREATE TRIGGER review_decision_immutable BEFORE UPDATE OR DELETE ON retail.review_decisions_v1
 FOR EACH ROW EXECUTE FUNCTION retail.reject_source_mutation();
CREATE TRIGGER review_decision_no_truncate BEFORE TRUNCATE ON retail.review_decisions_v1
 FOR EACH STATEMENT EXECUTE FUNCTION retail.reject_source_mutation();
CREATE TRIGGER review_event_immutable BEFORE UPDATE OR DELETE ON retail.review_decision_events_v1
 FOR EACH ROW EXECUTE FUNCTION retail.reject_source_mutation();
CREATE TRIGGER review_event_no_truncate BEFORE TRUNCATE ON retail.review_decision_events_v1
 FOR EACH STATEMENT EXECUTE FUNCTION retail.reject_source_mutation();
CREATE TRIGGER publication_intent_immutable BEFORE UPDATE OR DELETE ON retail.publication_outbox_v1
 FOR EACH ROW EXECUTE FUNCTION retail.reject_source_mutation();
CREATE TRIGGER publication_intent_no_truncate BEFORE TRUNCATE ON retail.publication_outbox_v1
 FOR EACH STATEMENT EXECUTE FUNCTION retail.reject_source_mutation();

CREATE FUNCTION retail.decision_snapshot_v1(p_case uuid,p_proposal uuid) RETURNS text
LANGUAGE sql STABLE SET search_path=pg_catalog,retail SET timezone='UTC' AS $function$
 SELECT jsonb_build_object('decision',d.payload_text::jsonb,'canonical_payload_text',d.payload_text,
   'decision_sha256',d.payload_sha256,'published',false,'dispatch_enabled',false,
   'audit_event',jsonb_build_object('event_id',e.event_id,'event_type',e.event_type,
     'reviewer_id',e.reviewer_id,'occurred_at',e.occurred_at),
   'outbox',CASE WHEN a.action_id IS NULL THEN NULL ELSE jsonb_build_object('action_id',a.action_id,
     'action_key',a.action_key,'state',a.state,'target_id',a.target_id,'relative_path',a.relative_path,
     'content_sha256',a.content_sha256,'content_bytes',a.content_bytes,
     'action_payload_sha256',a.action_payload_sha256,'authorization_expires_at',a.authorization_expires_at) END)::text
 FROM retail.review_decisions_v1 d JOIN retail.review_decision_events_v1 e USING(decision_id)
 LEFT JOIN retail.publication_outbox_v1 a USING(decision_id)
 WHERE d.case_id=p_case AND d.proposal_id=p_proposal;
$function$;

CREATE FUNCTION retail.api_decision_snapshot_v1(p_session text,p_case uuid,p_proposal uuid) RETURNS text
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,retail AS $function$
DECLARE identity uuid; result text;
BEGIN
 identity:=retail.api_portal_identity_v1(p_session);
 IF identity IS NULL THEN RAISE EXCEPTION 'Unauthorized' USING ERRCODE='42501'; END IF;
 result:=retail.decision_snapshot_v1(p_case,p_proposal);
 IF result IS NOT NULL AND (result::jsonb#>>'{decision,reviewer_id}')::uuid IS DISTINCT FROM identity THEN
   RAISE EXCEPTION 'Unauthorized' USING ERRCODE='42501';
 END IF;
 RETURN result;
END $function$;

CREATE FUNCTION retail.api_decide_request_v1(p_session text,p_csrf text,p_case uuid,p_proposal uuid,
 p_revision integer,p_report_hash text,p_proposal_hash text,p_choice text,p_key text) RETURNS text
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,retail SET timezone='UTC' AS $function$
DECLARE identity uuid; s retail.owner_portal_sessions%ROWTYPE; c retail.report_cases%ROWTYPE;
 r retail.approval_requests_v2%ROWTYPE; previous retail.review_decisions_v1%ROWTYPE;
 report retail.report_revisions%ROWTYPE; outcome text; decided timestamptz; id uuid; body text; action text;
BEGIN
 -- Authorize before revealing case/key/history. Lock against revoke/logout;
 -- any competing lock is retryable, never a new decision identity.
 identity:=retail.api_portal_identity_v1(p_session);
 IF identity IS NULL THEN RAISE EXCEPTION 'Unauthorized' USING ERRCODE='42501'; END IF;
 PERFORM 1 FROM retail.owner_credentials WHERE reviewer_id=identity AND revoked_at IS NULL FOR SHARE NOWAIT;
 IF NOT FOUND THEN RAISE EXCEPTION 'Unauthorized' USING ERRCODE='42501'; END IF;
 SELECT * INTO s FROM retail.owner_portal_sessions WHERE session_sha256=p_session FOR SHARE NOWAIT;
 IF s.session_sha256 IS NULL OR s.reviewer_id IS DISTINCT FROM identity OR s.revoked_at IS NOT NULL
    OR s.expires_at<=clock_timestamp() OR s.csrf_sha256 IS DISTINCT FROM p_csrf THEN
   RAISE EXCEPTION 'Unauthorized' USING ERRCODE='42501';
 END IF;
 IF p_case IS NULL OR p_proposal IS NULL OR p_revision IS DISTINCT FROM 1
   OR p_report_hash IS NULL OR p_report_hash !~ '^[a-f0-9]{64}$'
   OR p_proposal_hash IS NULL OR p_proposal_hash !~ '^[a-f0-9]{64}$'
   OR p_choice IS NULL OR p_choice NOT IN ('approve','reject','expire')
   OR p_key IS NULL OR p_key COLLATE "C" !~ '^[A-Za-z0-9_-]{8,128}$' THEN
   RAISE EXCEPTION 'Invalid decision' USING ERRCODE='22023';
 END IF;
 SELECT * INTO c FROM retail.report_cases WHERE case_id=p_case AND requester='local-service-v1' FOR UPDATE NOWAIT;
 IF NOT FOUND THEN RETURN NULL; END IF;
 SELECT * INTO r FROM retail.approval_requests_v2 WHERE proposal_id=p_proposal AND case_id=p_case;
 IF NOT FOUND THEN RETURN NULL; END IF;
 IF r.reviewer_id IS DISTINCT FROM identity THEN RAISE EXCEPTION 'Unauthorized' USING ERRCODE='42501'; END IF;
 IF r.report_revision IS DISTINCT FROM p_revision OR r.report_payload_sha256 IS DISTINCT FROM p_report_hash
    OR r.payload_sha256 IS DISTINCT FROM p_proposal_hash THEN
   RAISE EXCEPTION 'Decision binding conflict' USING ERRCODE='55000';
 END IF;
 outcome:=CASE p_choice WHEN 'approve' THEN 'approved' WHEN 'reject' THEN 'rejected' ELSE 'expired' END;
 SELECT * INTO previous FROM retail.review_decisions_v1 WHERE case_id=p_case AND decision_key=p_key;
 IF FOUND THEN
   IF previous.proposal_id IS DISTINCT FROM p_proposal OR previous.outcome IS DISTINCT FROM outcome
     OR previous.report_revision IS DISTINCT FROM p_revision OR previous.proposal_sha256 IS DISTINCT FROM p_proposal_hash
     OR previous.report_payload_sha256 IS DISTINCT FROM p_report_hash OR previous.reviewer_id IS DISTINCT FROM identity THEN
     RAISE EXCEPTION 'Decision key conflict' USING ERRCODE='55000';
   END IF;
   -- Historical replay is not fresh authorization; dispatch always rechecks.
   RETURN retail.decision_snapshot_v1(p_case,p_proposal);
 END IF;
 IF c.state<>'awaiting_approval' OR c.current_revision IS DISTINCT FROM p_revision
   OR EXISTS(SELECT 1 FROM retail.approval_requests_v2 WHERE predecessor_proposal_id=p_proposal)
   OR EXISTS(SELECT 1 FROM retail.review_decisions_v1 d WHERE d.proposal_id=p_proposal
     OR (d.case_id=p_case AND d.report_revision=p_revision AND d.outcome IN ('approved','rejected'))) THEN
   RAISE EXCEPTION 'Current undecided request required' USING ERRCODE='55000';
 END IF;
 SELECT * INTO STRICT report FROM retail.report_revisions WHERE case_id=p_case AND revision=p_revision;
 IF report.payload_sha256 IS DISTINCT FROM p_report_hash
   OR encode(sha256(convert_to(report.payload_text,'UTF8')),'hex') IS DISTINCT FROM p_report_hash
   OR octet_length(convert_to(report.payload_text,'UTF8')) IS DISTINCT FROM r.content_bytes
   OR r.payload_text IS DISTINCT FROM retail.approval_request_payload_v2(r.proposal_id,r.case_id,
     r.report_revision,r.report_payload_sha256,r.content_bytes,r.reviewer_id,r.created_at,r.expires_at,
     r.generation,r.request_key,r.predecessor_proposal_id,r.predecessor_proposal_sha256) THEN
   RAISE EXCEPTION 'Stored binding conflict' USING ERRCODE='55000';
 END IF;
 decided:=clock_timestamp();
 IF s.expires_at<=decided OR s.created_at>decided THEN RAISE EXCEPTION 'Unauthorized' USING ERRCODE='42501'; END IF;
 IF (outcome IN ('approved','rejected') AND decided>=r.expires_at)
   OR (outcome='expired' AND decided<r.expires_at) THEN
   RAISE EXCEPTION 'Request expiry conflict' USING ERRCODE='55000';
 END IF;
 id:=gen_random_uuid();
 body:=retail.decision_payload_v1(id,p_case,p_proposal,p_revision,p_proposal_hash,p_report_hash,
   identity,p_key,outcome,decided,r.expires_at);
 INSERT INTO retail.review_decisions_v1 VALUES(id,p_case,p_proposal,p_revision,p_proposal_hash,p_report_hash,
   identity,p_session,p_key,outcome,decided,r.expires_at,body,encode(sha256(convert_to(body,'UTF8')),'hex'));
 INSERT INTO retail.review_decision_events_v1(decision_id,event_type,reviewer_id,occurred_at)
   VALUES(id,'review_'||outcome,identity,decided);
 IF outcome='approved' THEN
   action:=(r.payload_text::jsonb->'action')::text;
   INSERT INTO retail.publication_outbox_v1(action_key,decision_id,proposal_id,case_id,report_revision,
     action_type,target_id,relative_path,content_text,content_sha256,content_bytes,action_payload_text,
     action_payload_sha256,proposal_sha256,created_at,authorization_expires_at)
   VALUES('publish-local-v1:'||p_proposal::text,id,p_proposal,p_case,p_revision,
     'publish_local_report_json_v1','local-approved-report-json-v1',
     'reports/approved/v1/'||p_case::text||'/revision-1.json',report.payload_text,p_report_hash,r.content_bytes,
     action,encode(sha256(convert_to(action,'UTF8')),'hex'),p_proposal_hash,decided,r.expires_at);
 END IF;
 RETURN retail.decision_snapshot_v1(p_case,p_proposal);
END $function$;

REVOKE ALL ON FUNCTION retail.guard_review_decision_v1(),retail.guard_review_event_v1(),
 retail.guard_publication_intent_v1(),retail.guard_decision_bundle_v1(),retail.reject_terminal_successor_v1(),
 retail.decision_snapshot_v1(uuid,uuid),retail.api_decision_snapshot_v1(text,uuid,uuid),
 retail.api_decide_request_v1(text,text,uuid,uuid,integer,text,text,text,text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION retail.api_decision_snapshot_v1(text,uuid,uuid),
 retail.api_decide_request_v1(text,text,uuid,uuid,integer,text,text,text,text) TO raa_wp4_decision_api;
-- Deliberately no grants to service, reviewer or portal roles, and no LOGIN.
INSERT INTO retail.schema_migrations(version,name) VALUES(19,'decision_outbox_foundation');
