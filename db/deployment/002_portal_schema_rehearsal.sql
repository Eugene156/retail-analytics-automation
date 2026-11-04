-- Static, clone-only deployment002. New guard/receipt; no test guard rewrite.
-- Contract DDL below is retained verbatim from reviewed022-029 bodies.
DO $deployment_guard$
DECLARE suffix text:=substring(current_database() from '^raa_wp4_populated_rehearsal_([a-f0-9]{12})$');
BEGIN
 IF suffix IS NULL OR current_user IS DISTINCT FROM ('rehearsal_admin_'||suffix)
  OR session_user IS DISTINCT FROM current_user OR pg_is_in_recovery()
  OR (SELECT system_identifier::text FROM pg_control_system()) IS DISTINCT FROM current_setting('raa.rehearsal_system',true)
  OR coalesce(current_setting('raa.rehearsal_system',true),'') !~ '^[0-9]{10,20}$'
  OR coalesce(current_setting('raa.checkpoint_id',true),'') !~ '^[a-f0-9]{8}(-[a-f0-9]{4}){3}-[a-f0-9]{12}$'
  OR coalesce(current_setting('raa.deployment_id',true),'') !~ '^[a-f0-9]{8}(-[a-f0-9]{4}){3}-[a-f0-9]{12}$'
  OR coalesce(current_setting('raa.predecessor_id',true),'') !~ '^[a-f0-9]{8}(-[a-f0-9]{4}){3}-[a-f0-9]{12}$'
  OR coalesce(current_setting('raa.source_digest',true),'') !~ '^[a-f0-9]{64}$'
  OR coalesce(current_setting('raa.bundle_digest',true),'') !~ '^[a-f0-9]{64}$'
  OR coalesce(current_setting('raa.predecessor_digest',true),'') !~ '^[a-f0-9]{64}$'
  OR coalesce(current_setting('raa.baseline_digest',true),'') !~ '^[a-f0-9]{64}$' THEN
  RAISE EXCEPTION 'Exact populated rehearsal context required';
 END IF;
 IF NOT pg_try_advisory_xact_lock(hashtextextended('wp4-populated-deployment001',0)) THEN
  RAISE EXCEPTION 'Deployment is busy' USING ERRCODE='55P03'; END IF;
 IF to_regclass('raa_deployment.releases') IS NULL THEN
  RAISE EXCEPTION 'Committed deployment001 required'; END IF;
 IF NOT EXISTS(SELECT FROM raa_deployment.releases r WHERE r.bundle_id='wp4-rehearsal-001'
  AND r.deployment_id=current_setting('raa.predecessor_id')::uuid
  AND r.checkpoint_id=current_setting('raa.checkpoint_id')::uuid
  AND r.bundle_digest=current_setting('raa.predecessor_digest')
  AND r.source_digest=current_setting('raa.source_digest') AND r.baseline_digest=current_setting('raa.baseline_digest')
  AND r.target_system=current_setting('raa.rehearsal_system') AND r.target_database=current_database()
  AND r.admitted=false AND r.base_version=20)
  OR (SELECT count(*) FROM raa_deployment.releases)<>1
  OR (SELECT array_agg(version ORDER BY version) FROM retail.schema_migrations) IS DISTINCT FROM ARRAY(SELECT generate_series(1,20))
  OR to_regclass('raa_deployment.portal_schema_releases') IS NOT NULL
  OR to_regclass('retail.portal_approval_requests_v3') IS NOT NULL
  OR to_regclass('retail.publication_dispatch_events_v1') IS NULL
  OR EXISTS(SELECT FROM retail.publication_dispatch_events_v1)
  OR EXISTS(SELECT FROM retail.review_decisions_v1) OR EXISTS(SELECT FROM retail.publication_outbox_v1)
  OR (SELECT count(*) FROM retail.owner_credentials WHERE revoked_at IS NULL)<>1
  OR NOT EXISTS(SELECT FROM retail.approval_policies p JOIN retail.owner_credentials o USING(reviewer_id)
      WHERE p.policy_version='local-publication-v1' AND p.ttl_seconds=86400 AND o.revoked_at IS NULL)
  OR EXISTS(SELECT FROM pg_roles WHERE (rolname='g0_user' OR rolname LIKE 'raa\_%' ESCAPE '\')
      AND (rolcanlogin OR rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication OR rolbypassrls))
  OR EXISTS(SELECT FROM pg_auth_members m JOIN pg_roles a ON a.oid=m.roleid JOIN pg_roles b ON b.oid=m.member
      WHERE a.rolname='g0_user' OR b.rolname='g0_user' OR a.rolname LIKE 'raa\_%' ESCAPE '\'
      OR b.rolname LIKE 'raa\_%' ESCAPE '\' OR a.rolname=current_user OR b.rolname=current_user) THEN
  RAISE EXCEPTION 'Exact non-admitted populated001 predecessor required';
 END IF;
END $deployment_guard$;

-- Roles are internal NOLOGIN contract principals, never application admission.
DO $contract_roles$
DECLARE role_name text;
BEGIN
 FOREACH role_name IN ARRAY ARRAY['raa_wp4_portal_issue_v3','raa_wp4_portal_review_v2','raa_wp4_portal_publish_v2',
  'raa_wp4_portal_read_v2','raa_wp4_portal_transition_v1','raa_wp4_portal_auth_v2','raa_wp4_portal_worker_v2',
  'raa_wp4_portal_attempt_v1','raa_wp4_portal_recovery_v1'] LOOP
  IF NOT EXISTS(SELECT FROM pg_roles WHERE rolname=role_name) THEN
   EXECUTE format('CREATE ROLE %I NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS',role_name);
  END IF;
  EXECUTE format('GRANT CONNECT ON DATABASE %I TO %I',current_database(),role_name);
  EXECUTE format('GRANT USAGE ON SCHEMA retail TO %I',role_name);
 END LOOP;
 EXECUTE format('REVOKE CREATE,TEMPORARY ON DATABASE %I FROM PUBLIC',current_database());
END $contract_roles$;
SET LOCAL ROLE g0_user;

-- BEGIN STATIC REVIEWED CONTRACT BODIES
-- Reviewed contract DDL: 022_portal_publication_foundation.sql
CREATE TABLE retail.portal_publication_policies_v2 (
 policy_version text PRIMARY KEY CHECK(policy_version='owner-portal-acceptance-v2'),
 reviewer_id uuid NOT NULL REFERENCES retail.owner_credentials(reviewer_id),
 ttl_seconds integer NOT NULL CHECK(ttl_seconds=86400)
);
CREATE TABLE retail.portal_approval_requests_v3 (
 request_id uuid PRIMARY KEY,
 case_id uuid NOT NULL,
 revision integer NOT NULL CHECK(revision=1),
 reviewer_id uuid NOT NULL REFERENCES retail.owner_credentials(reviewer_id),
 policy_version text NOT NULL REFERENCES retail.portal_publication_policies_v2(policy_version),
 generation integer NOT NULL CHECK(generation>0),
 request_key text NOT NULL CHECK(request_key COLLATE "C" ~ '^[A-Za-z0-9_-]{8,128}$'),
 predecessor_id uuid UNIQUE REFERENCES retail.portal_approval_requests_v3(request_id),
 predecessor_sha256 text CHECK(predecessor_sha256 ~ '^[a-f0-9]{64}$'),
 created_at timestamptz NOT NULL CHECK(isfinite(created_at)),
 expires_at timestamptz NOT NULL CHECK(isfinite(expires_at)),
 report_sha256 text NOT NULL CHECK(report_sha256 ~ '^[a-f0-9]{64}$'),
 content_bytes integer NOT NULL CHECK(content_bytes BETWEEN 1 AND 131072),
 payload_text text NOT NULL CHECK(payload_text=payload_text::jsonb::text AND octet_length(payload_text)<=32768),
 payload_sha256 text NOT NULL CHECK(payload_sha256=encode(sha256(convert_to(payload_text,'UTF8')),'hex')),
 FOREIGN KEY(case_id,revision) REFERENCES retail.report_revisions(case_id,revision),
 UNIQUE(case_id,request_key), UNIQUE(case_id,revision,generation),
 CHECK(expires_at=created_at+interval '86400 seconds'),
 CHECK((generation=1 AND predecessor_id IS NULL AND predecessor_sha256 IS NULL)
  OR (generation>1 AND predecessor_id IS NOT NULL AND predecessor_sha256 IS NOT NULL))
);
CREATE TABLE retail.portal_review_decisions_v2 (
 decision_id uuid PRIMARY KEY,
 request_id uuid NOT NULL UNIQUE REFERENCES retail.portal_approval_requests_v3(request_id),
 session_sha256 text NOT NULL REFERENCES retail.owner_portal_sessions(session_sha256),
 decision_key text NOT NULL CHECK(decision_key COLLATE "C" ~ '^[A-Za-z0-9_-]{8,128}$'),
 outcome text NOT NULL CHECK(outcome IN ('approved','rejected')),
 decided_at timestamptz NOT NULL CHECK(isfinite(decided_at)),
 UNIQUE(request_id,decision_key)
);
CREATE TABLE retail.portal_publication_intents_v2 (
 action_id uuid PRIMARY KEY,
 decision_id uuid NOT NULL UNIQUE REFERENCES retail.portal_review_decisions_v2(decision_id),
 request_id uuid NOT NULL UNIQUE REFERENCES retail.portal_approval_requests_v3(request_id),
 target_id text NOT NULL CHECK(target_id='local-owner-portal-report-v2'),
 action_type text NOT NULL CHECK(action_type='publish_owner_portal_report_v2'),
 content_text text NOT NULL,
 content_sha256 text NOT NULL CHECK(content_sha256=encode(sha256(convert_to(content_text,'UTF8')),'hex')),
 content_bytes integer NOT NULL CHECK(content_bytes=octet_length(convert_to(content_text,'UTF8')) AND content_bytes BETWEEN 1 AND 131072)
);
CREATE TABLE retail.portal_publications_v2 (
 publication_id uuid PRIMARY KEY,
 action_id uuid NOT NULL UNIQUE REFERENCES retail.portal_publication_intents_v2(action_id),
 case_id uuid NOT NULL,
 revision integer NOT NULL CHECK(revision=1),
 target_id text NOT NULL CHECK(target_id='local-owner-portal-report-v2'),
 acceptance_key text NOT NULL CHECK(acceptance_key COLLATE "C" ~ '^[A-Za-z0-9_-]{8,128}$'),
 accepted_at timestamptz NOT NULL CHECK(isfinite(accepted_at)),
 UNIQUE(case_id,revision,target_id),
 FOREIGN KEY(case_id,revision) REFERENCES retail.report_revisions(case_id,revision)
);
CREATE TABLE retail.portal_publication_audit_v2 (
 event_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 subject_id uuid NOT NULL UNIQUE,
 kind text NOT NULL CHECK(kind IN ('request_created','review_approved','review_rejected','publication_accepted')),
 occurred_at timestamptz NOT NULL CHECK(isfinite(occurred_at))
);

CREATE FUNCTION retail.portal_request_payload_v3(p_id uuid,p_case uuid,p_hash text,p_bytes integer,
 p_owner uuid,p_created timestamptz,p_expires timestamptz,p_generation integer,p_key text,p_parent uuid,p_parent_hash text)
RETURNS text LANGUAGE sql STABLE SET search_path=pg_catalog,retail SET timezone='UTC' AS $fn$
 SELECT (retail.approval_request_payload_v2(p_id,p_case,1,p_hash,p_bytes,p_owner,p_created,p_expires,
  p_generation,p_key,p_parent,p_parent_hash)::jsonb || jsonb_build_object(
  'contract_version','owner-portal-approval-request-v3','review_policy_version','owner-portal-acceptance-v2',
  'publication_semantics','guarded-server-acceptance-v1','action',jsonb_build_object(
   'type','publish_owner_portal_report_v2','content_sha256',p_hash,'content_bytes',p_bytes,
   'target',jsonb_build_object('target_id','local-owner-portal-report-v2','media_type','application/json'))))::text;
$fn$;

CREATE FUNCTION retail.portal_lock_case_v2(p_case uuid) RETURNS uuid
LANGUAGE plpgsql VOLATILE SET search_path=pg_catalog,retail AS $fn$
DECLARE owner_id uuid;
BEGIN
 SELECT reviewer_id INTO owner_id FROM retail.portal_publication_policies_v2 WHERE policy_version='owner-portal-acceptance-v2';
 IF owner_id IS NULL THEN RAISE EXCEPTION 'Portal policy unavailable' USING ERRCODE='55000'; END IF;
 PERFORM 1 FROM retail.owner_credentials WHERE reviewer_id=owner_id AND revoked_at IS NULL FOR SHARE NOWAIT;
 IF NOT FOUND THEN RAISE EXCEPTION 'Unauthorized' USING ERRCODE='42501'; END IF;
 PERFORM 1 FROM retail.report_cases WHERE case_id=p_case AND requester='local-service-v1'
  AND state='awaiting_approval' AND current_revision=1 FOR UPDATE NOWAIT;
 IF NOT FOUND THEN RAISE EXCEPTION 'Current report required' USING ERRCODE='55000'; END IF;
 RETURN owner_id;
END $fn$;

CREATE FUNCTION retail.guard_portal_request_v3() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,retail AS $fn$
DECLARE owner_id uuid; report retail.report_revisions%ROWTYPE; previous retail.portal_approval_requests_v3%ROWTYPE;
BEGIN
 owner_id:=retail.portal_lock_case_v2(NEW.case_id);
 SELECT * INTO STRICT report FROM retail.report_revisions WHERE case_id=NEW.case_id AND revision=1;
 SELECT * INTO previous FROM retail.portal_approval_requests_v3 WHERE case_id=NEW.case_id ORDER BY generation DESC LIMIT 1;
 IF NEW.reviewer_id IS DISTINCT FROM owner_id OR NEW.policy_version<>'owner-portal-acceptance-v2'
  OR NEW.generation IS DISTINCT FROM coalesce(previous.generation,0)+1
  OR NEW.predecessor_id IS DISTINCT FROM previous.request_id
  OR NEW.predecessor_sha256 IS DISTINCT FROM previous.payload_sha256
  OR (previous.request_id IS NOT NULL AND NEW.created_at<previous.expires_at)
  OR EXISTS(SELECT 1 FROM retail.portal_review_decisions_v2 WHERE request_id=previous.request_id AND outcome='rejected')
  OR EXISTS(SELECT 1 FROM retail.portal_publications_v2 WHERE case_id=NEW.case_id)
  OR EXISTS(SELECT 1 FROM retail.approval_proposals WHERE case_id=NEW.case_id)
  OR EXISTS(SELECT 1 FROM retail.approval_requests_v2 WHERE case_id=NEW.case_id)
  OR report.schema_version<>'deterministic-comparison-report-v1'
  OR NEW.report_sha256 IS DISTINCT FROM report.payload_sha256
  OR report.payload_sha256 IS DISTINCT FROM encode(sha256(convert_to(report.payload_text,'UTF8')),'hex')
  OR NEW.content_bytes IS DISTINCT FROM octet_length(convert_to(report.payload_text,'UTF8'))
  OR NEW.created_at<timestamptz '2000-01-01 UTC' OR NEW.created_at>clock_timestamp()
  OR NEW.payload_text IS DISTINCT FROM retail.portal_request_payload_v3(NEW.request_id,NEW.case_id,NEW.report_sha256,
   NEW.content_bytes,NEW.reviewer_id,NEW.created_at,NEW.expires_at,NEW.generation,NEW.request_key,
   NEW.predecessor_id,NEW.predecessor_sha256) THEN
  RAISE EXCEPTION 'New-target request binding conflict' USING ERRCODE='55000';
 END IF;
 RETURN NEW;
END $fn$;
CREATE TRIGGER portal_request_binding BEFORE INSERT ON retail.portal_approval_requests_v3
 FOR EACH ROW EXECUTE FUNCTION retail.guard_portal_request_v3();

CREATE FUNCTION retail.guard_portal_decision_v2() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,retail AS $fn$
DECLARE r retail.portal_approval_requests_v3%ROWTYPE; owner_id uuid; s retail.owner_portal_sessions%ROWTYPE;
BEGIN
 SELECT * INTO STRICT r FROM retail.portal_approval_requests_v3 WHERE request_id=NEW.request_id;
 owner_id:=retail.portal_lock_case_v2(r.case_id);
 SELECT * INTO s FROM retail.owner_portal_sessions WHERE session_sha256=NEW.session_sha256 FOR SHARE NOWAIT;
 IF r.reviewer_id IS DISTINCT FROM owner_id OR s.reviewer_id IS DISTINCT FROM owner_id
  OR retail.api_portal_identity_v1(NEW.session_sha256) IS DISTINCT FROM owner_id
  OR s.revoked_at IS NOT NULL OR NEW.decided_at<s.created_at OR NEW.decided_at>=s.expires_at
  OR NEW.decided_at<r.created_at OR NEW.decided_at>=r.expires_at OR NEW.decided_at>clock_timestamp()
  OR EXISTS(SELECT 1 FROM retail.portal_approval_requests_v3 WHERE predecessor_id=r.request_id) THEN
  RAISE EXCEPTION 'Current owner decision required' USING ERRCODE='55000';
 END IF;
 RETURN NEW;
END $fn$;
CREATE TRIGGER portal_decision_binding BEFORE INSERT ON retail.portal_review_decisions_v2
 FOR EACH ROW EXECUTE FUNCTION retail.guard_portal_decision_v2();

CREATE FUNCTION retail.guard_portal_intent_v2() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,retail AS $fn$
DECLARE d retail.portal_review_decisions_v2%ROWTYPE; r retail.portal_approval_requests_v3%ROWTYPE; report retail.report_revisions%ROWTYPE;
BEGIN
 SELECT * INTO STRICT d FROM retail.portal_review_decisions_v2 WHERE decision_id=NEW.decision_id;
 SELECT * INTO STRICT r FROM retail.portal_approval_requests_v3 WHERE request_id=d.request_id;
 SELECT * INTO STRICT report FROM retail.report_revisions WHERE case_id=r.case_id AND revision=r.revision;
 IF d.outcome<>'approved' OR NEW.request_id IS DISTINCT FROM r.request_id
  OR NEW.content_text IS DISTINCT FROM report.payload_text OR NEW.content_sha256 IS DISTINCT FROM r.report_sha256
  OR NEW.content_bytes IS DISTINCT FROM r.content_bytes THEN
  RAISE EXCEPTION 'Exact new-target approval required' USING ERRCODE='55000';
 END IF;
 RETURN NEW;
END $fn$;
CREATE TRIGGER portal_intent_binding BEFORE INSERT ON retail.portal_publication_intents_v2
 FOR EACH ROW EXECUTE FUNCTION retail.guard_portal_intent_v2();

CREATE FUNCTION retail.portal_acceptance_in_window_v2(p_created timestamptz,p_expires timestamptz,p_sample timestamptz)
RETURNS boolean LANGUAGE sql IMMUTABLE SET search_path=pg_catalog AS $fn$
 SELECT coalesce(isfinite(p_created) AND isfinite(p_expires) AND isfinite(p_sample)
  AND p_expires=p_created+interval '86400 seconds' AND p_sample>=p_created AND p_sample<p_expires,false);
$fn$;

CREATE FUNCTION retail.guard_portal_acceptance_v2() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,retail AS $fn$
DECLARE a retail.portal_publication_intents_v2%ROWTYPE; r retail.portal_approval_requests_v3%ROWTYPE;
 d retail.portal_review_decisions_v2%ROWTYPE; report retail.report_revisions%ROWTYPE; owner_id uuid; now_at timestamptz;
BEGIN
 SELECT * INTO STRICT a FROM retail.portal_publication_intents_v2 WHERE action_id=NEW.action_id;
 SELECT * INTO STRICT r FROM retail.portal_approval_requests_v3 WHERE request_id=a.request_id;
 owner_id:=retail.portal_lock_case_v2(r.case_id);
 PERFORM 1 FROM retail.portal_publication_intents_v2 WHERE action_id=a.action_id FOR UPDATE NOWAIT;
 SELECT * INTO STRICT d FROM retail.portal_review_decisions_v2 WHERE decision_id=a.decision_id;
 SELECT * INTO STRICT report FROM retail.report_revisions WHERE case_id=r.case_id AND revision=r.revision;
 IF NEW.case_id IS DISTINCT FROM r.case_id OR NEW.revision IS DISTINCT FROM r.revision
  OR d.request_id IS DISTINCT FROM r.request_id OR d.outcome<>'approved' OR r.reviewer_id IS DISTINCT FROM owner_id
  OR d.decided_at<r.created_at OR d.decided_at>=r.expires_at
  OR EXISTS(SELECT 1 FROM retail.portal_approval_requests_v3 WHERE predecessor_id=r.request_id)
  OR a.content_text IS DISTINCT FROM report.payload_text OR a.content_sha256 IS DISTINCT FROM r.report_sha256
  OR report.payload_sha256 IS DISTINCT FROM r.report_sha256 OR a.content_bytes IS DISTINCT FROM r.content_bytes
  OR r.payload_text IS DISTINCT FROM retail.portal_request_payload_v3(r.request_id,r.case_id,r.report_sha256,
   r.content_bytes,r.reviewer_id,r.created_at,r.expires_at,r.generation,r.request_key,r.predecessor_id,r.predecessor_sha256) THEN
  RAISE EXCEPTION 'Current exact acceptance binding required' USING ERRCODE='55000';
 END IF;
 -- Linearization point: ONE fresh server clock sample after locks/binding.
 -- Caller accepted_at is never used. Event effective only on eventual commit.
 now_at:=clock_timestamp();
 IF NOT retail.portal_acceptance_in_window_v2(r.created_at,r.expires_at,now_at) THEN
  RAISE EXCEPTION 'Publication acceptance deadline expired' USING ERRCODE='55000';
 END IF;
 NEW.accepted_at:=now_at;
 RETURN NEW;
END $fn$;
CREATE TRIGGER portal_acceptance_binding BEFORE INSERT ON retail.portal_publications_v2
 FOR EACH ROW EXECUTE FUNCTION retail.guard_portal_acceptance_v2();

CREATE FUNCTION retail.guard_portal_audit_v2() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,retail AS $fn$
DECLARE expected_kind text; expected_time timestamptz;
BEGIN
 SELECT 'request_created',created_at INTO expected_kind,expected_time FROM retail.portal_approval_requests_v3 WHERE request_id=NEW.subject_id;
 IF NOT FOUND THEN
  SELECT 'review_'||outcome,decided_at INTO expected_kind,expected_time FROM retail.portal_review_decisions_v2 WHERE decision_id=NEW.subject_id;
 END IF;
 IF expected_kind IS NULL THEN
  SELECT 'publication_accepted',accepted_at INTO expected_kind,expected_time FROM retail.portal_publications_v2 WHERE publication_id=NEW.subject_id;
 END IF;
 IF expected_kind IS NULL OR NEW.kind IS DISTINCT FROM expected_kind OR NEW.occurred_at IS DISTINCT FROM expected_time THEN
  RAISE EXCEPTION 'Audit binding conflict';
 END IF;
 RETURN NEW;
END $fn$;
CREATE TRIGGER portal_audit_binding BEFORE INSERT ON retail.portal_publication_audit_v2
 FOR EACH ROW EXECUTE FUNCTION retail.guard_portal_audit_v2();

CREATE FUNCTION retail.guard_portal_bundle_v2() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,retail AS $fn$
DECLARE subject uuid; expected_kind text; expected_time timestamptz;
BEGIN
 subject:=CASE TG_TABLE_NAME WHEN 'portal_approval_requests_v3' THEN (to_jsonb(NEW)->>'request_id')::uuid
  WHEN 'portal_review_decisions_v2' THEN (to_jsonb(NEW)->>'decision_id')::uuid ELSE (to_jsonb(NEW)->>'publication_id')::uuid END;
 expected_kind:=CASE TG_TABLE_NAME WHEN 'portal_approval_requests_v3' THEN 'request_created'
  WHEN 'portal_review_decisions_v2' THEN 'review_'||(to_jsonb(NEW)->>'outcome') ELSE 'publication_accepted' END;
 expected_time:=CASE TG_TABLE_NAME WHEN 'portal_approval_requests_v3' THEN (to_jsonb(NEW)->>'created_at')::timestamptz
  WHEN 'portal_review_decisions_v2' THEN (to_jsonb(NEW)->>'decided_at')::timestamptz ELSE (to_jsonb(NEW)->>'accepted_at')::timestamptz END;
 IF NOT EXISTS(SELECT 1 FROM retail.portal_publication_audit_v2 WHERE subject_id=subject
  AND kind=expected_kind AND occurred_at=expected_time) THEN
  RAISE EXCEPTION 'Atomic audit bundle required';
 END IF;
 IF TG_TABLE_NAME='portal_review_decisions_v2' AND
  ((to_jsonb(NEW)->>'outcome'='approved') IS DISTINCT FROM
   EXISTS(SELECT 1 FROM retail.portal_publication_intents_v2 WHERE decision_id=subject)) THEN
  RAISE EXCEPTION 'Atomic decision intent bundle required';
 END IF;
 RETURN NULL;
END $fn$;

CREATE FUNCTION retail.portal_request_snapshot_v3(p_request uuid) RETURNS text
LANGUAGE sql STABLE SET search_path=pg_catalog,retail AS $fn$
 SELECT jsonb_build_object('request',r.payload_text::jsonb,'canonical_payload_text',r.payload_text,
 'request_sha256',r.payload_sha256,'decision',d.outcome,'decision_id',d.decision_id,'action_id',a.action_id,
 'is_current',NOT EXISTS(SELECT 1 FROM retail.portal_approval_requests_v3 n WHERE n.predecessor_id=r.request_id),
 'publication',CASE WHEN p.publication_id IS NULL THEN NULL ELSE jsonb_build_object(
  'publication_id',p.publication_id,'accepted_at',p.accepted_at,'target_id',p.target_id) END,
 'dispatch_enabled',false)::text FROM retail.portal_approval_requests_v3 r
 LEFT JOIN retail.portal_review_decisions_v2 d USING(request_id)
 LEFT JOIN retail.portal_publication_intents_v2 a USING(request_id)
 LEFT JOIN retail.portal_publications_v2 p USING(action_id) WHERE r.request_id=p_request;
$fn$;

CREATE FUNCTION retail.api_issue_portal_request_v3(p_case uuid,p_hash text,p_key text,p_parent uuid) RETURNS text
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,retail AS $fn$
DECLARE owner_id uuid; report retail.report_revisions%ROWTYPE; old retail.portal_approval_requests_v3%ROWTYPE;
 previous retail.portal_approval_requests_v3%ROWTYPE; id uuid:=gen_random_uuid(); now_at timestamptz; body text; size integer; generation integer;
BEGIN
 IF p_case IS NULL OR p_hash IS NULL OR p_hash !~ '^[a-f0-9]{64}$' OR p_key IS NULL
  OR p_key COLLATE "C" !~ '^[A-Za-z0-9_-]{8,128}$' THEN RAISE EXCEPTION 'Invalid request' USING ERRCODE='22023'; END IF;
 owner_id:=retail.portal_lock_case_v2(p_case);
 SELECT * INTO STRICT report FROM retail.report_revisions WHERE case_id=p_case AND revision=1;
 IF report.payload_sha256 IS DISTINCT FROM p_hash THEN RAISE EXCEPTION 'Report conflict' USING ERRCODE='55000'; END IF;
 SELECT * INTO old FROM retail.portal_approval_requests_v3 WHERE case_id=p_case AND request_key=p_key;
 IF FOUND THEN
  IF old.report_sha256 IS DISTINCT FROM p_hash OR old.predecessor_id IS DISTINCT FROM p_parent THEN
   RAISE EXCEPTION 'Request key conflict' USING ERRCODE='55000'; END IF;
  RETURN retail.portal_request_snapshot_v3(old.request_id);
 END IF;
 SELECT * INTO previous FROM retail.portal_approval_requests_v3 WHERE case_id=p_case ORDER BY generation DESC LIMIT 1;
 now_at:=clock_timestamp(); generation:=coalesce(previous.generation,0)+1;
 IF p_parent IS DISTINCT FROM previous.request_id OR (previous.request_id IS NOT NULL AND now_at<previous.expires_at) THEN
  RAISE EXCEPTION 'Expired latest predecessor required' USING ERRCODE='55000'; END IF;
 size:=octet_length(convert_to(report.payload_text,'UTF8'));
 body:=retail.portal_request_payload_v3(id,p_case,p_hash,size,owner_id,now_at,now_at+interval '86400 seconds',
  generation,p_key,p_parent,previous.payload_sha256);
 INSERT INTO retail.portal_approval_requests_v3 VALUES(id,p_case,1,owner_id,'owner-portal-acceptance-v2',generation,
  p_key,p_parent,previous.payload_sha256,now_at,now_at+interval '86400 seconds',p_hash,size,body,
  encode(sha256(convert_to(body,'UTF8')),'hex'));
 INSERT INTO retail.portal_publication_audit_v2(subject_id,kind,occurred_at) VALUES(id,'request_created',now_at);
 RETURN retail.portal_request_snapshot_v3(id);
END $fn$;

CREATE FUNCTION retail.api_decide_portal_request_v2(p_session text,p_csrf text,p_request uuid,p_hash text,p_choice text,p_key text) RETURNS text
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,retail AS $fn$
DECLARE identity uuid; r retail.portal_approval_requests_v3%ROWTYPE; old retail.portal_review_decisions_v2%ROWTYPE;
 s retail.owner_portal_sessions%ROWTYPE; report retail.report_revisions%ROWTYPE; id uuid:=gen_random_uuid(); outcome text; now_at timestamptz;
BEGIN
 identity:=retail.api_portal_identity_v1(p_session);
 IF identity IS NULL THEN RAISE EXCEPTION 'Unauthorized' USING ERRCODE='42501'; END IF;
 IF p_request IS NULL OR p_hash IS NULL OR p_hash !~ '^[a-f0-9]{64}$' OR p_choice IS NULL OR p_choice NOT IN ('approve','reject')
  OR p_key IS NULL OR p_key COLLATE "C" !~ '^[A-Za-z0-9_-]{8,128}$' THEN RAISE EXCEPTION 'Invalid decision' USING ERRCODE='22023'; END IF;
 SELECT * INTO STRICT r FROM retail.portal_approval_requests_v3 WHERE request_id=p_request;
 IF retail.portal_lock_case_v2(r.case_id) IS DISTINCT FROM identity OR r.reviewer_id IS DISTINCT FROM identity THEN
  RAISE EXCEPTION 'Unauthorized' USING ERRCODE='42501'; END IF;
 SELECT * INTO s FROM retail.owner_portal_sessions WHERE session_sha256=p_session FOR SHARE NOWAIT;
 IF s.csrf_sha256 IS DISTINCT FROM p_csrf OR s.revoked_at IS NOT NULL OR s.expires_at<=clock_timestamp() THEN
  RAISE EXCEPTION 'Unauthorized' USING ERRCODE='42501'; END IF;
 IF r.payload_sha256 IS DISTINCT FROM p_hash THEN RAISE EXCEPTION 'Request hash conflict' USING ERRCODE='55000'; END IF;
 outcome:=CASE p_choice WHEN 'approve' THEN 'approved' ELSE 'rejected' END;
 SELECT * INTO old FROM retail.portal_review_decisions_v2 WHERE request_id=p_request;
 IF FOUND THEN
  IF old.decision_key IS DISTINCT FROM p_key OR old.outcome IS DISTINCT FROM outcome THEN
   RAISE EXCEPTION 'Decision key conflict' USING ERRCODE='55000'; END IF;
  RETURN retail.portal_request_snapshot_v3(p_request);
 END IF;
 now_at:=clock_timestamp();
 INSERT INTO retail.portal_review_decisions_v2 VALUES(id,p_request,p_session,p_key,outcome,now_at);
 INSERT INTO retail.portal_publication_audit_v2(subject_id,kind,occurred_at) VALUES(id,'review_'||outcome,now_at);
 IF outcome='approved' THEN
  SELECT * INTO STRICT report FROM retail.report_revisions WHERE case_id=r.case_id AND revision=1;
  INSERT INTO retail.portal_publication_intents_v2 VALUES(gen_random_uuid(),id,p_request,'local-owner-portal-report-v2',
   'publish_owner_portal_report_v2',report.payload_text,r.report_sha256,r.content_bytes);
 END IF;
 RETURN retail.portal_request_snapshot_v3(p_request);
END $fn$;

CREATE FUNCTION retail.api_accept_portal_publication_v2(p_action uuid,p_key text) RETURNS text
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,retail AS $fn$
DECLARE a retail.portal_publication_intents_v2%ROWTYPE; r retail.portal_approval_requests_v3%ROWTYPE;
 old retail.portal_publications_v2%ROWTYPE; id uuid:=gen_random_uuid(); accepted timestamptz;
BEGIN
 IF p_action IS NULL OR p_key IS NULL OR p_key COLLATE "C" !~ '^[A-Za-z0-9_-]{8,128}$' THEN
  RAISE EXCEPTION 'Invalid acceptance' USING ERRCODE='22023'; END IF;
 SELECT * INTO STRICT a FROM retail.portal_publication_intents_v2 WHERE action_id=p_action;
 SELECT * INTO STRICT r FROM retail.portal_approval_requests_v3 WHERE request_id=a.request_id;
 PERFORM retail.portal_lock_case_v2(r.case_id);
 SELECT * INTO old FROM retail.portal_publications_v2 WHERE action_id=p_action;
 IF FOUND THEN
  IF old.acceptance_key IS DISTINCT FROM p_key THEN RAISE EXCEPTION 'Acceptance key conflict' USING ERRCODE='55000'; END IF;
  RETURN retail.portal_request_snapshot_v3(r.request_id);
 END IF;
 INSERT INTO retail.portal_publications_v2 VALUES(id,p_action,r.case_id,r.revision,'local-owner-portal-report-v2',p_key,
  clock_timestamp()) RETURNING accepted_at INTO accepted;
 INSERT INTO retail.portal_publication_audit_v2(subject_id,kind,occurred_at) VALUES(id,'publication_accepted',accepted);
 RETURN retail.portal_request_snapshot_v3(r.request_id);
END $fn$;

CREATE FUNCTION retail.api_portal_publication_state_v2(p_action uuid) RETURNS text
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,retail AS $fn$
DECLARE r retail.portal_approval_requests_v3%ROWTYPE;
BEGIN
 SELECT q.* INTO r FROM retail.portal_publication_intents_v2 a JOIN retail.portal_approval_requests_v3 q USING(request_id) WHERE action_id=p_action;
 IF NOT FOUND THEN RETURN NULL; END IF;
 IF NOT EXISTS(SELECT 1 FROM retail.owner_credentials WHERE reviewer_id=r.reviewer_id AND revoked_at IS NULL) THEN
  RAISE EXCEPTION 'Unauthorized' USING ERRCODE='42501'; END IF;
 RETURN retail.portal_request_snapshot_v3(r.request_id);
END $fn$;

DO $seal$
DECLARE table_name text; function_row record;
BEGIN
 FOREACH table_name IN ARRAY ARRAY['portal_publication_policies_v2','portal_approval_requests_v3','portal_review_decisions_v2',
  'portal_publication_intents_v2','portal_publications_v2','portal_publication_audit_v2'] LOOP
  EXECUTE format('REVOKE ALL ON TABLE retail.%I FROM PUBLIC',table_name);
  EXECUTE format('CREATE TRIGGER immutable BEFORE UPDATE OR DELETE ON retail.%I FOR EACH ROW EXECUTE FUNCTION retail.reject_source_mutation()',table_name);
  EXECUTE format('CREATE TRIGGER no_truncate BEFORE TRUNCATE ON retail.%I FOR EACH STATEMENT EXECUTE FUNCTION retail.reject_source_mutation()',table_name);
 END LOOP;
 FOREACH table_name IN ARRAY ARRAY['portal_approval_requests_v3','portal_review_decisions_v2','portal_publications_v2'] LOOP
  EXECUTE format('CREATE CONSTRAINT TRIGGER atomic_bundle AFTER INSERT ON retail.%I DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION retail.guard_portal_bundle_v2()',table_name);
 END LOOP;
 FOR function_row IN SELECT p.oid::regprocedure AS signature FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
  WHERE n.nspname='retail' AND p.proname IN ('portal_request_payload_v3','portal_lock_case_v2','guard_portal_request_v3',
   'guard_portal_decision_v2','guard_portal_intent_v2','guard_portal_acceptance_v2','guard_portal_audit_v2',
   'guard_portal_bundle_v2','portal_acceptance_in_window_v2','portal_request_snapshot_v3','api_issue_portal_request_v3','api_decide_portal_request_v2',
   'api_accept_portal_publication_v2','api_portal_publication_state_v2') LOOP
  EXECUTE format('REVOKE ALL ON FUNCTION %s FROM PUBLIC',function_row.signature);
 END LOOP;
END $seal$;
GRANT EXECUTE ON FUNCTION retail.api_issue_portal_request_v3(uuid,text,text,uuid) TO raa_wp4_portal_issue_v3;
GRANT EXECUTE ON FUNCTION retail.api_decide_portal_request_v2(text,text,uuid,text,text,text) TO raa_wp4_portal_review_v2;
GRANT EXECUTE ON FUNCTION retail.api_accept_portal_publication_v2(uuid,text),retail.api_portal_publication_state_v2(uuid) TO raa_wp4_portal_publish_v2;

-- Reviewed contract DDL: 023_portal_publication_reads.sql
GRANT USAGE ON SCHEMA retail TO raa_wp4_portal_read_v2;

CREATE FUNCTION retail.portal_owner_identity_v2(p_session text) RETURNS uuid
LANGUAGE plpgsql VOLATILE SET search_path=pg_catalog,retail AS $fn$
DECLARE identity uuid; s retail.owner_portal_sessions%ROWTYPE; now_at timestamptz;
BEGIN
 identity:=retail.api_portal_identity_v1(p_session);
 IF identity IS NULL THEN RAISE EXCEPTION 'Unauthorized' USING ERRCODE='42501'; END IF;
 PERFORM 1 FROM retail.owner_credentials WHERE reviewer_id=identity AND revoked_at IS NULL FOR SHARE NOWAIT;
 IF NOT FOUND THEN RAISE EXCEPTION 'Unauthorized' USING ERRCODE='42501'; END IF;
 SELECT * INTO s FROM retail.owner_portal_sessions WHERE session_sha256=p_session FOR SHARE NOWAIT;
 now_at:=clock_timestamp();
 IF s.reviewer_id IS DISTINCT FROM identity OR s.revoked_at IS NOT NULL
  OR s.created_at>now_at OR s.expires_at<=now_at THEN
  RAISE EXCEPTION 'Unauthorized' USING ERRCODE='42501'; END IF;
 RETURN identity;
END $fn$;

CREATE FUNCTION retail.api_owner_portal_request_v3(p_session text,p_request uuid) RETURNS text
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,retail AS $fn$
DECLARE identity uuid; r retail.portal_approval_requests_v3%ROWTYPE;
BEGIN
 identity:=retail.portal_owner_identity_v2(p_session);
 SELECT * INTO r FROM retail.portal_approval_requests_v3 WHERE request_id=p_request;
 IF NOT FOUND THEN RETURN NULL; END IF;
 IF r.reviewer_id IS DISTINCT FROM identity THEN RAISE EXCEPTION 'Unauthorized' USING ERRCODE='42501'; END IF;
 RETURN retail.portal_request_snapshot_v3(p_request);
END $fn$;

CREATE FUNCTION retail.portal_owner_publication_v2(p_session text,p_action uuid,p_export boolean) RETURNS text
LANGUAGE plpgsql VOLATILE SET search_path=pg_catalog,retail AS $fn$
DECLARE identity uuid; r retail.portal_approval_requests_v3%ROWTYPE; a retail.portal_publication_intents_v2%ROWTYPE;
BEGIN
 identity:=retail.portal_owner_identity_v2(p_session);
 SELECT q.* INTO r FROM retail.portal_approval_requests_v3 q
  JOIN retail.portal_publication_intents_v2 i USING(request_id) WHERE i.action_id=p_action;
 IF NOT FOUND THEN RETURN NULL; END IF;
 IF r.reviewer_id IS DISTINCT FROM identity THEN RAISE EXCEPTION 'Unauthorized' USING ERRCODE='42501'; END IF;
 IF NOT EXISTS(SELECT 1 FROM retail.portal_publications_v2 WHERE action_id=p_action) THEN RETURN NULL; END IF;
 SELECT * INTO STRICT a FROM retail.portal_publication_intents_v2 WHERE action_id=p_action;
 RETURN jsonb_build_object('receipt',retail.portal_request_snapshot_v3(r.request_id)::jsonb,
  'content_text',CASE WHEN p_export THEN a.content_text ELSE NULL END)::text;
END $fn$;

CREATE FUNCTION retail.api_owner_portal_receipt_v2(p_session text,p_action uuid) RETURNS text
LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,retail AS $fn$
 SELECT retail.portal_owner_publication_v2(p_session,p_action,false);
$fn$;
CREATE FUNCTION retail.api_owner_portal_export_v2(p_session text,p_action uuid) RETURNS text
LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,retail AS $fn$
 SELECT retail.portal_owner_publication_v2(p_session,p_action,true);
$fn$;

REVOKE ALL ON FUNCTION retail.portal_owner_identity_v2(text),retail.portal_owner_publication_v2(text,uuid,boolean),
 retail.api_owner_portal_request_v3(text,uuid),retail.api_owner_portal_receipt_v2(text,uuid),
 retail.api_owner_portal_export_v2(text,uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION retail.api_portal_identity_v1(text),retail.api_owner_portal_request_v3(text,uuid),
 retail.api_owner_portal_receipt_v2(text,uuid),retail.api_owner_portal_export_v2(text,uuid) TO raa_wp4_portal_read_v2;

-- Reviewed contract DDL: 024_portal_review_projections.sql
CREATE FUNCTION retail.portal_review_snapshot_v3(p_request uuid) RETURNS text
LANGUAGE plpgsql VOLATILE SET search_path=pg_catalog,retail SET timezone='UTC' AS $fn$
DECLARE r retail.portal_approval_requests_v3%ROWTYPE; d retail.portal_review_decisions_v2%ROWTYPE;
 body jsonb; observed timestamptz:=clock_timestamp(); status text; report text;
BEGIN
 SELECT * INTO r FROM retail.portal_approval_requests_v3 WHERE request_id=p_request;
 IF NOT FOUND THEN RETURN NULL; END IF;
 body:=retail.portal_request_snapshot_v3(p_request)::jsonb;
 SELECT * INTO d FROM retail.portal_review_decisions_v2 WHERE request_id=p_request;
 status:=CASE WHEN body->'publication'<>'null'::jsonb THEN 'published'
  WHEN d.outcome='rejected' THEN 'rejected'
  WHEN NOT (body->>'is_current')::boolean THEN 'superseded'
  WHEN observed>=r.expires_at THEN CASE WHEN d.outcome='approved' THEN 'approved_expired' ELSE 'expired' END
  WHEN d.outcome='approved' THEN 'approved_pending_publication' ELSE 'pending_review' END;
 SELECT payload_text INTO STRICT report FROM retail.report_revisions WHERE case_id=r.case_id AND revision=r.revision;
 RETURN (body || jsonb_build_object('observed_at',observed,'review_status',status,
  'decision_enabled',status='pending_review' AND observed>=r.created_at,
  'report_text',report,'review_receipt',CASE WHEN d.decision_id IS NULL THEN NULL ELSE jsonb_build_object(
   'decision_id',d.decision_id,'request_id',r.request_id,'request_sha256',r.payload_sha256,
   'report_sha256',r.report_sha256,'reviewer_id',r.reviewer_id,'outcome',d.outcome,
   'decided_at',d.decided_at,'decision_key',d.decision_key,'target_id','local-owner-portal-report-v2') END))::text;
END $fn$;

CREATE FUNCTION retail.api_owner_portal_review_v3(p_session text,p_case uuid,p_request uuid) RETURNS text
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,retail AS $fn$
DECLARE identity uuid; r retail.portal_approval_requests_v3%ROWTYPE;
BEGIN
 identity:=retail.portal_owner_identity_v2(p_session);
 SELECT * INTO r FROM retail.portal_approval_requests_v3 WHERE request_id=p_request AND case_id=p_case;
 IF NOT FOUND THEN RETURN NULL; END IF;
 IF r.reviewer_id IS DISTINCT FROM identity THEN RAISE EXCEPTION 'Unauthorized' USING ERRCODE='42501'; END IF;
 RETURN retail.portal_review_snapshot_v3(p_request);
END $fn$;

CREATE FUNCTION retail.api_owner_portal_requests_v3(p_session text) RETURNS text
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,retail SET timezone='UTC' AS $fn$
DECLARE identity uuid; result text;
BEGIN
 identity:=retail.portal_owner_identity_v2(p_session);
 SELECT coalesce(jsonb_agg(jsonb_build_object('case_id',case_id,'request_id',request_id,'generation',generation,
  'expires_at',expires_at,'review_status',retail.portal_review_snapshot_v3(request_id)::jsonb->>'review_status')
  ORDER BY created_at DESC,request_id),'[]'::jsonb)::text INTO result FROM (
   SELECT r.* FROM retail.portal_approval_requests_v3 r WHERE r.reviewer_id=identity
   AND NOT EXISTS(SELECT 1 FROM retail.portal_approval_requests_v3 n WHERE n.predecessor_id=r.request_id)
   ORDER BY r.created_at DESC,r.request_id LIMIT 20) latest;
 RETURN result;
END $fn$;

CREATE FUNCTION retail.api_owner_decide_portal_request_v3(p_session text,p_csrf text,p_case uuid,
 p_request uuid,p_report_hash text,p_request_hash text,p_choice text,p_key text) RETURNS text
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,retail AS $fn$
DECLARE identity uuid; r retail.portal_approval_requests_v3%ROWTYPE;
BEGIN
 identity:=retail.api_portal_identity_v1(p_session);
 IF identity IS NULL THEN RAISE EXCEPTION 'Unauthorized' USING ERRCODE='42501'; END IF;
 SELECT * INTO r FROM retail.portal_approval_requests_v3 WHERE request_id=p_request;
 IF NOT FOUND THEN RETURN NULL; END IF;
 IF r.reviewer_id IS DISTINCT FROM identity THEN RAISE EXCEPTION 'Unauthorized' USING ERRCODE='42501'; END IF;
 IF r.case_id IS DISTINCT FROM p_case OR r.report_sha256 IS DISTINCT FROM p_report_hash THEN
  RAISE EXCEPTION 'Exact report binding required' USING ERRCODE='55000'; END IF;
 PERFORM retail.api_decide_portal_request_v2(p_session,p_csrf,p_request,p_request_hash,p_choice,p_key);
 RETURN retail.portal_review_snapshot_v3(p_request);
END $fn$;

REVOKE ALL ON FUNCTION retail.portal_review_snapshot_v3(uuid),retail.api_owner_portal_review_v3(text,uuid,uuid),
 retail.api_owner_portal_requests_v3(text),retail.api_owner_decide_portal_request_v3(text,text,uuid,uuid,text,text,text,text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION retail.api_owner_portal_review_v3(text,uuid,uuid),retail.api_owner_portal_requests_v3(text)
 TO raa_wp4_portal_read_v2;
GRANT EXECUTE ON FUNCTION retail.api_owner_decide_portal_request_v3(text,text,uuid,uuid,text,text,text,text)
 TO raa_wp4_portal_review_v2;

-- Reviewed contract DDL: 025_portal_legacy_transition.sql
CREATE TABLE retail.portal_legacy_transitions_v1 (
 transition_id uuid PRIMARY KEY,
 case_id uuid NOT NULL UNIQUE REFERENCES retail.report_cases(case_id),
 legacy_request_id uuid NOT NULL UNIQUE REFERENCES retail.approval_requests_v2(proposal_id),
 legacy_request_sha256 text NOT NULL CHECK(legacy_request_sha256 ~ '^[a-f0-9]{64}$'),
 first_request_id uuid NOT NULL UNIQUE REFERENCES retail.portal_approval_requests_v3(request_id) DEFERRABLE INITIALLY DEFERRED,
 first_request_sha256 text NOT NULL CHECK(first_request_sha256 ~ '^[a-f0-9]{64}$'),
 report_sha256 text NOT NULL CHECK(report_sha256 ~ '^[a-f0-9]{64}$'),
 reviewer_id uuid NOT NULL REFERENCES retail.owner_credentials(reviewer_id),
 request_key text NOT NULL CHECK(request_key COLLATE "C" ~ '^[A-Za-z0-9_-]{8,128}$'),
 transitioned_at timestamptz NOT NULL CHECK(isfinite(transitioned_at)),
 payload_text text NOT NULL CHECK(payload_text=payload_text::jsonb::text AND octet_length(payload_text)<=8192),
 payload_sha256 text NOT NULL CHECK(payload_sha256=encode(sha256(convert_to(payload_text,'UTF8')),'hex'))
);
CREATE TABLE retail.portal_legacy_transition_events_v1 (
 event_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 transition_id uuid NOT NULL UNIQUE REFERENCES retail.portal_legacy_transitions_v1(transition_id),
 kind text NOT NULL CHECK(kind='legacy_target_retired'),
 occurred_at timestamptz NOT NULL CHECK(isfinite(occurred_at))
);

CREATE FUNCTION retail.portal_transition_payload_v1(p_id uuid,p_case uuid,p_old uuid,p_old_hash text,
 p_new uuid,p_new_hash text,p_report_hash text,p_owner uuid,p_key text,p_time timestamptz)
RETURNS text LANGUAGE sql STABLE SET search_path=pg_catalog SET timezone='UTC' AS $fn$
 SELECT jsonb_build_object('contract_version','portal-legacy-transition-v1','transition_id',p_id,'case_id',p_case,
  'legacy_request_id',p_old,'legacy_request_sha256',p_old_hash,'legacy_target_id','local-approved-report-json-v1',
  'first_request_id',p_new,'first_request_sha256',p_new_hash,'target_id','local-owner-portal-report-v2',
  'report_revision',1,'report_sha256',p_report_hash,'reviewer_id',p_owner,'request_key',p_key,
  'transitioned_at',to_char(p_time AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
  'approval_transferred',false,'legacy_files_adopted',false)::text;
$fn$;

CREATE FUNCTION retail.guard_portal_transition_v1() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,retail AS $fn$
DECLARE owner_id uuid; old retail.approval_requests_v2%ROWTYPE; report retail.report_revisions%ROWTYPE;
BEGIN
 owner_id:=retail.portal_lock_case_v2(NEW.case_id);
 SELECT * INTO old FROM retail.approval_requests_v2 WHERE case_id=NEW.case_id ORDER BY generation DESC LIMIT 1;
 SELECT * INTO STRICT report FROM retail.report_revisions WHERE case_id=NEW.case_id AND revision=1;
 IF old.proposal_id IS NULL OR old.proposal_id IS DISTINCT FROM NEW.legacy_request_id
  OR old.payload_sha256 IS DISTINCT FROM NEW.legacy_request_sha256 OR old.reviewer_id IS DISTINCT FROM owner_id
  OR NEW.reviewer_id IS DISTINCT FROM owner_id OR old.review_policy_version<>'local-publication-v1'
  OR old.report_revision<>1 OR old.report_payload_sha256 IS DISTINCT FROM NEW.report_sha256
  OR report.payload_sha256 IS DISTINCT FROM NEW.report_sha256
  OR report.payload_sha256 IS DISTINCT FROM encode(sha256(convert_to(report.payload_text,'UTF8')),'hex')
  OR report.schema_version<>'deterministic-comparison-report-v1'
  OR old.content_bytes IS DISTINCT FROM octet_length(convert_to(report.payload_text,'UTF8'))
  OR old.expires_at IS DISTINCT FROM old.created_at+interval '86400 seconds'
  OR old.expires_at>NEW.transitioned_at OR NEW.transitioned_at>clock_timestamp()
  OR NEW.transitioned_at<timestamptz '2000-01-01 UTC'
  OR old.payload_text IS DISTINCT FROM retail.approval_request_payload_v2(old.proposal_id,old.case_id,1,
   old.report_payload_sha256,old.content_bytes,old.reviewer_id,old.created_at,old.expires_at,
   old.generation,old.request_key,old.predecessor_proposal_id,old.predecessor_proposal_sha256)
  OR NOT EXISTS(SELECT 1 FROM retail.approval_request_events_v2 WHERE proposal_id=old.proposal_id AND occurred_at=old.created_at)
  OR EXISTS(SELECT 1 FROM retail.approval_proposals WHERE case_id=NEW.case_id)
  OR EXISTS(SELECT 1 FROM retail.review_decisions_v1 WHERE case_id=NEW.case_id)
  OR EXISTS(SELECT 1 FROM retail.publication_outbox_v1 WHERE case_id=NEW.case_id)
  OR EXISTS(SELECT 1 FROM retail.portal_approval_requests_v3 WHERE case_id=NEW.case_id)
  OR NEW.payload_text IS DISTINCT FROM retail.portal_transition_payload_v1(NEW.transition_id,NEW.case_id,
   NEW.legacy_request_id,NEW.legacy_request_sha256,NEW.first_request_id,NEW.first_request_sha256,
   NEW.report_sha256,NEW.reviewer_id,NEW.request_key,NEW.transitioned_at) THEN
  RAISE EXCEPTION 'Expired unreviewed latest legacy request required' USING ERRCODE='55000';
 END IF;
 RETURN NEW;
END $fn$;
CREATE TRIGGER transition_binding BEFORE INSERT ON retail.portal_legacy_transitions_v1
 FOR EACH ROW EXECUTE FUNCTION retail.guard_portal_transition_v1();

-- Preserve every original request guard, except the deliberately narrow
-- explicit-transition exception. Original canonical v3 request bytes unchanged.
CREATE OR REPLACE FUNCTION retail.guard_portal_request_v3() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,retail AS $fn$
DECLARE owner_id uuid; report retail.report_revisions%ROWTYPE; previous retail.portal_approval_requests_v3%ROWTYPE;
BEGIN
 owner_id:=retail.portal_lock_case_v2(NEW.case_id);
 SELECT * INTO STRICT report FROM retail.report_revisions WHERE case_id=NEW.case_id AND revision=1;
 SELECT * INTO previous FROM retail.portal_approval_requests_v3 WHERE case_id=NEW.case_id ORDER BY generation DESC LIMIT 1;
 IF NEW.reviewer_id IS DISTINCT FROM owner_id OR NEW.policy_version<>'owner-portal-acceptance-v2'
  OR NEW.generation IS DISTINCT FROM coalesce(previous.generation,0)+1
  OR NEW.predecessor_id IS DISTINCT FROM previous.request_id
  OR NEW.predecessor_sha256 IS DISTINCT FROM previous.payload_sha256
  OR (previous.request_id IS NOT NULL AND NEW.created_at<previous.expires_at)
  OR EXISTS(SELECT 1 FROM retail.portal_review_decisions_v2 WHERE request_id=previous.request_id AND outcome='rejected')
  OR EXISTS(SELECT 1 FROM retail.portal_publications_v2 WHERE case_id=NEW.case_id)
  OR EXISTS(SELECT 1 FROM retail.approval_proposals WHERE case_id=NEW.case_id)
  OR (EXISTS(SELECT 1 FROM retail.approval_requests_v2 WHERE case_id=NEW.case_id) AND NOT EXISTS(
   SELECT 1 FROM retail.portal_legacy_transitions_v1 t WHERE t.case_id=NEW.case_id
    AND t.reviewer_id=NEW.reviewer_id AND t.report_sha256=NEW.report_sha256
    AND ((NEW.generation=1 AND t.first_request_id=NEW.request_id AND t.first_request_sha256=NEW.payload_sha256
     AND t.request_key=NEW.request_key AND t.transitioned_at=NEW.created_at)
     OR (NEW.generation>1 AND EXISTS(SELECT 1 FROM retail.portal_approval_requests_v3 first
      WHERE first.request_id=t.first_request_id AND first.payload_sha256=t.first_request_sha256)))))
  OR report.schema_version<>'deterministic-comparison-report-v1'
  OR NEW.report_sha256 IS DISTINCT FROM report.payload_sha256
  OR report.payload_sha256 IS DISTINCT FROM encode(sha256(convert_to(report.payload_text,'UTF8')),'hex')
  OR NEW.content_bytes IS DISTINCT FROM octet_length(convert_to(report.payload_text,'UTF8'))
  OR NEW.created_at<timestamptz '2000-01-01 UTC' OR NEW.created_at>clock_timestamp()
  OR NEW.payload_text IS DISTINCT FROM retail.portal_request_payload_v3(NEW.request_id,NEW.case_id,NEW.report_sha256,
   NEW.content_bytes,NEW.reviewer_id,NEW.created_at,NEW.expires_at,NEW.generation,NEW.request_key,
   NEW.predecessor_id,NEW.predecessor_sha256) THEN
  RAISE EXCEPTION 'New-target request binding conflict' USING ERRCODE='55000';
 END IF;
 RETURN NEW;
END $fn$;

CREATE FUNCTION retail.fence_legacy_portal_writes_v1() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,retail AS $fn$
DECLARE cid uuid;
BEGIN
 IF TG_TABLE_NAME='publication_dispatch_events_v1' THEN
  SELECT case_id INTO STRICT cid FROM retail.publication_outbox_v1 WHERE action_id=NEW.action_id;
 ELSE cid:=(to_jsonb(NEW)->>'case_id')::uuid; END IF;
 PERFORM 1 FROM retail.report_cases WHERE case_id=cid FOR UPDATE NOWAIT;
 IF EXISTS(SELECT 1 FROM retail.portal_legacy_transitions_v1 WHERE case_id=cid)
  OR EXISTS(SELECT 1 FROM retail.portal_approval_requests_v3 WHERE case_id=cid) THEN
  RAISE EXCEPTION 'Legacy target retired for this case' USING ERRCODE='55000';
 END IF;
 RETURN NEW;
END $fn$;
DO $fences$
DECLARE tab text;
BEGIN
 FOREACH tab IN ARRAY ARRAY['approval_proposals','approval_requests_v2','review_decisions_v1',
  'publication_outbox_v1','publication_dispatch_events_v1'] LOOP
  EXECUTE format('CREATE TRIGGER a_portal_transition_fence BEFORE INSERT ON retail.%I FOR EACH ROW EXECUTE FUNCTION retail.fence_legacy_portal_writes_v1()',tab);
 END LOOP;
END $fences$;

CREATE FUNCTION retail.guard_portal_transition_event_v1() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,retail AS $fn$
BEGIN
 IF NOT EXISTS(SELECT 1 FROM retail.portal_legacy_transitions_v1 WHERE transition_id=NEW.transition_id
  AND transitioned_at=NEW.occurred_at) THEN RAISE EXCEPTION 'Transition audit binding conflict'; END IF;
 RETURN NEW;
END $fn$;
CREATE TRIGGER event_binding BEFORE INSERT ON retail.portal_legacy_transition_events_v1
 FOR EACH ROW EXECUTE FUNCTION retail.guard_portal_transition_event_v1();

CREATE FUNCTION retail.guard_portal_transition_bundle_v1() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,retail AS $fn$
BEGIN
 IF NOT EXISTS(SELECT 1 FROM retail.portal_approval_requests_v3 r WHERE r.request_id=NEW.first_request_id
  AND r.case_id=NEW.case_id AND r.reviewer_id=NEW.reviewer_id AND r.generation=1 AND r.predecessor_id IS NULL
  AND r.report_sha256=NEW.report_sha256 AND r.payload_sha256=NEW.first_request_sha256
  AND r.request_key=NEW.request_key AND r.created_at=NEW.transitioned_at)
  OR NOT EXISTS(SELECT 1 FROM retail.portal_legacy_transition_events_v1 WHERE transition_id=NEW.transition_id
   AND kind='legacy_target_retired' AND occurred_at=NEW.transitioned_at) THEN
  RAISE EXCEPTION 'Atomic transition request/audit bundle required';
 END IF;
 RETURN NULL;
END $fn$;
CREATE CONSTRAINT TRIGGER atomic_transition AFTER INSERT ON retail.portal_legacy_transitions_v1
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION retail.guard_portal_transition_bundle_v1();

CREATE FUNCTION retail.portal_transition_snapshot_v1(p_case uuid) RETURNS text
LANGUAGE sql STABLE SET search_path=pg_catalog,retail AS $fn$
 SELECT jsonb_build_object('transition',t.payload_text::jsonb,'canonical_transition_text',t.payload_text,
  'transition_sha256',t.payload_sha256,'new_request',retail.portal_request_snapshot_v3(t.first_request_id)::jsonb)::text
 FROM retail.portal_legacy_transitions_v1 t WHERE case_id=p_case;
$fn$;

CREATE FUNCTION retail.api_transition_legacy_portal_v1(p_case uuid,p_old uuid,p_old_hash text,p_report_hash text,p_key text)
RETURNS text LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,retail SET timezone='UTC' AS $fn$
DECLARE owner_id uuid; t retail.portal_legacy_transitions_v1%ROWTYPE; report retail.report_revisions%ROWTYPE;
 tid uuid:=gen_random_uuid(); rid uuid:=gen_random_uuid(); now_at timestamptz; body text; digest text; transition_body text; size integer;
BEGIN
 IF p_case IS NULL OR p_old IS NULL OR p_old_hash IS NULL OR p_old_hash !~ '^[a-f0-9]{64}$'
  OR p_report_hash IS NULL OR p_report_hash !~ '^[a-f0-9]{64}$' OR p_key IS NULL
  OR p_key COLLATE "C" !~ '^[A-Za-z0-9_-]{8,128}$' THEN RAISE EXCEPTION 'Invalid transition' USING ERRCODE='22023'; END IF;
 owner_id:=retail.portal_lock_case_v2(p_case);
 SELECT * INTO t FROM retail.portal_legacy_transitions_v1 WHERE case_id=p_case;
 IF FOUND THEN
  IF t.legacy_request_id IS DISTINCT FROM p_old OR t.legacy_request_sha256 IS DISTINCT FROM p_old_hash
   OR t.report_sha256 IS DISTINCT FROM p_report_hash OR t.request_key IS DISTINCT FROM p_key
   OR t.reviewer_id IS DISTINCT FROM owner_id THEN RAISE EXCEPTION 'Transition key/binding conflict' USING ERRCODE='55000'; END IF;
  RETURN retail.portal_transition_snapshot_v1(p_case);
 END IF;
 SELECT * INTO STRICT report FROM retail.report_revisions WHERE case_id=p_case AND revision=1;
 now_at:=clock_timestamp(); size:=octet_length(convert_to(report.payload_text,'UTF8'));
 body:=retail.portal_request_payload_v3(rid,p_case,p_report_hash,size,owner_id,now_at,now_at+interval '86400 seconds',1,p_key,NULL,NULL);
 digest:=encode(sha256(convert_to(body,'UTF8')),'hex');
 transition_body:=retail.portal_transition_payload_v1(tid,p_case,p_old,p_old_hash,rid,digest,p_report_hash,owner_id,p_key,now_at);
 INSERT INTO retail.portal_legacy_transitions_v1 VALUES(tid,p_case,p_old,p_old_hash,rid,digest,p_report_hash,owner_id,p_key,
  now_at,transition_body,encode(sha256(convert_to(transition_body,'UTF8')),'hex'));
 INSERT INTO retail.portal_approval_requests_v3 VALUES(rid,p_case,1,owner_id,'owner-portal-acceptance-v2',1,p_key,NULL,NULL,
  now_at,now_at+interval '86400 seconds',p_report_hash,size,body,digest);
 INSERT INTO retail.portal_publication_audit_v2(subject_id,kind,occurred_at) VALUES(rid,'request_created',now_at);
 INSERT INTO retail.portal_legacy_transition_events_v1(transition_id,kind,occurred_at) VALUES(tid,'legacy_target_retired',now_at);
 RETURN retail.portal_transition_snapshot_v1(p_case);
END $fn$;

CREATE FUNCTION retail.api_owner_portal_transition_v1(p_session text,p_case uuid) RETURNS text
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,retail AS $fn$
DECLARE identity uuid; t retail.portal_legacy_transitions_v1%ROWTYPE;
BEGIN
 identity:=retail.portal_owner_identity_v2(p_session);
 SELECT * INTO t FROM retail.portal_legacy_transitions_v1 WHERE case_id=p_case;
 IF NOT FOUND THEN RETURN NULL; END IF;
 IF t.reviewer_id IS DISTINCT FROM identity THEN RAISE EXCEPTION 'Unauthorized' USING ERRCODE='42501'; END IF;
 RETURN retail.portal_transition_snapshot_v1(p_case);
END $fn$;

DO $seal$
DECLARE tab text; fn record;
BEGIN
 FOREACH tab IN ARRAY ARRAY['portal_legacy_transitions_v1','portal_legacy_transition_events_v1'] LOOP
  EXECUTE format('REVOKE ALL ON TABLE retail.%I FROM PUBLIC',tab);
  EXECUTE format('CREATE TRIGGER immutable BEFORE UPDATE OR DELETE ON retail.%I FOR EACH ROW EXECUTE FUNCTION retail.reject_source_mutation()',tab);
  EXECUTE format('CREATE TRIGGER no_truncate BEFORE TRUNCATE ON retail.%I FOR EACH STATEMENT EXECUTE FUNCTION retail.reject_source_mutation()',tab);
 END LOOP;
 FOR fn IN SELECT p.oid::regprocedure AS signature FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
  WHERE n.nspname='retail' AND p.proname IN ('portal_transition_payload_v1','guard_portal_transition_v1',
  'fence_legacy_portal_writes_v1','guard_portal_transition_event_v1','guard_portal_transition_bundle_v1',
  'portal_transition_snapshot_v1','api_transition_legacy_portal_v1','api_owner_portal_transition_v1') LOOP
  EXECUTE format('REVOKE ALL ON FUNCTION %s FROM PUBLIC',fn.signature);
 END LOOP;
END $seal$;
GRANT EXECUTE ON FUNCTION retail.api_transition_legacy_portal_v1(uuid,uuid,text,text,text) TO raa_wp4_portal_transition_v1;
GRANT EXECUTE ON FUNCTION retail.api_owner_portal_transition_v1(text,uuid) TO raa_wp4_portal_read_v2;

-- Reviewed contract DDL: 026_portal_transition_reads.sql
CREATE FUNCTION retail.api_portal_transition_state_v1(p_case uuid,p_key text) RETURNS text
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,retail AS $fn$
DECLARE owner_id uuid; t retail.portal_legacy_transitions_v1%ROWTYPE;
BEGIN
 IF p_case IS NULL OR p_key IS NULL OR p_key COLLATE "C" !~ '^[A-Za-z0-9_-]{8,128}$' THEN
  RAISE EXCEPTION 'Invalid transition identity' USING ERRCODE='22023'; END IF;
 owner_id:=retail.portal_lock_case_v2(p_case);
 SELECT * INTO t FROM retail.portal_legacy_transitions_v1 WHERE case_id=p_case;
 IF NOT FOUND THEN RETURN NULL; END IF;
 IF t.reviewer_id IS DISTINCT FROM owner_id THEN RAISE EXCEPTION 'Unauthorized' USING ERRCODE='42501'; END IF;
 IF t.request_key IS DISTINCT FROM p_key THEN RAISE EXCEPTION 'Original transition key required' USING ERRCODE='55000'; END IF;
 RETURN retail.portal_transition_snapshot_v1(p_case);
END $fn$;

CREATE FUNCTION retail.api_owner_retired_legacy_request_v1(p_session text,p_case uuid,p_old uuid) RETURNS text
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,retail SET timezone='UTC' AS $fn$
DECLARE identity uuid; t retail.portal_legacy_transitions_v1%ROWTYPE; r retail.approval_requests_v2%ROWTYPE;
 e retail.approval_request_events_v2%ROWTYPE;
BEGIN
 identity:=retail.portal_owner_identity_v2(p_session);
 SELECT * INTO t FROM retail.portal_legacy_transitions_v1 WHERE case_id=p_case;
 IF NOT FOUND THEN RETURN NULL; END IF;
 IF t.reviewer_id IS DISTINCT FROM identity THEN RAISE EXCEPTION 'Unauthorized' USING ERRCODE='42501'; END IF;
 SELECT * INTO r FROM retail.approval_requests_v2 WHERE proposal_id=p_old AND case_id=p_case;
 IF NOT FOUND THEN RETURN NULL; END IF;
 IF r.reviewer_id IS DISTINCT FROM identity THEN RAISE EXCEPTION 'Unauthorized' USING ERRCODE='42501'; END IF;
 SELECT * INTO STRICT e FROM retail.approval_request_events_v2 WHERE proposal_id=p_old;
 RETURN (retail.portal_transition_snapshot_v1(p_case)::jsonb || jsonb_build_object(
  'legacy_status','retired','decision_enabled',false,'legacy_published',false,
  'legacy_request',jsonb_build_object('request',r.payload_text::jsonb,'canonical_payload_text',r.payload_text,
   'request_sha256',r.payload_sha256,'creation_event',jsonb_build_object('event_id',e.event_id,
    'event_type',e.event_type,'occurred_at',e.occurred_at,'actor',e.actor))))::text;
END $fn$;

REVOKE ALL ON FUNCTION retail.api_portal_transition_state_v1(uuid,text),
 retail.api_owner_retired_legacy_request_v1(text,uuid,uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION retail.api_portal_transition_state_v1(uuid,text) TO raa_wp4_portal_transition_v1;
GRANT EXECUTE ON FUNCTION retail.api_owner_retired_legacy_request_v1(text,uuid,uuid) TO raa_wp4_portal_read_v2;

-- Reviewed contract DDL: 027_portal_auth_v2.sql
GRANT USAGE ON SCHEMA retail TO raa_wp4_portal_auth_v2;

CREATE FUNCTION retail.api_portal_auth_identity_v2(p_session text) RETURNS uuid
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,retail AS $fn$
DECLARE identity uuid;
BEGIN
 identity:=retail.portal_owner_identity_v2(p_session);
 IF NOT EXISTS(SELECT 1 FROM retail.portal_publication_policies_v2
  WHERE policy_version='owner-portal-acceptance-v2' AND ttl_seconds=86400 AND reviewer_id=identity) THEN
  RAISE EXCEPTION 'Unauthorized' USING ERRCODE='42501'; END IF;
 RETURN identity;
END $fn$;

CREATE FUNCTION retail.api_portal_auth_login_v2(p_owner text,p_session text,p_csrf text,p_old text) RETURNS text
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,retail SET timezone='UTC' AS $fn$
DECLARE identity uuid; s retail.owner_portal_sessions%ROWTYPE;
BEGIN
 -- Existing owner UPDATE lock serializes rotation/cap/revocation. Validate the
 -- separate new-target policy before invoking the unchanged auth-state function.
 SELECT c.reviewer_id INTO identity FROM retail.owner_credentials c
 JOIN retail.portal_publication_policies_v2 p ON p.reviewer_id=c.reviewer_id
  AND p.policy_version='owner-portal-acceptance-v2' AND p.ttl_seconds=86400
 WHERE c.token_sha256=p_owner AND c.revoked_at IS NULL FOR UPDATE OF c NOWAIT;
 IF identity IS NULL THEN RAISE EXCEPTION 'Unauthorized' USING ERRCODE='42501'; END IF;
 IF retail.api_portal_login_v1(p_owner,p_session,p_csrf,p_old) IS DISTINCT FROM identity THEN
  RAISE EXCEPTION 'Unauthorized' USING ERRCODE='42501'; END IF;
 SELECT * INTO STRICT s FROM retail.owner_portal_sessions WHERE session_sha256=p_session;
 RETURN jsonb_build_object('reviewer_id',identity,'created_at',s.created_at,'expires_at',s.expires_at)::text;
END $fn$;

CREATE FUNCTION retail.api_portal_auth_logout_v2(p_session text,p_csrf text) RETURNS boolean
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,retail AS $fn$
BEGIN
 -- Fresh clock and owner/session SHARE locks through the logout transaction.
 PERFORM retail.api_portal_auth_identity_v2(p_session);
 RETURN retail.api_portal_logout_v1(p_session,p_csrf);
END $fn$;
REVOKE ALL ON FUNCTION retail.api_portal_auth_identity_v2(text),
 retail.api_portal_auth_login_v2(text,text,text,text),retail.api_portal_auth_logout_v2(text,text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION retail.api_portal_auth_identity_v2(text),
 retail.api_portal_auth_login_v2(text,text,text,text),retail.api_portal_auth_logout_v2(text,text) TO raa_wp4_portal_auth_v2;

-- Reviewed contract DDL: 028_portal_worker_boundary.sql
GRANT USAGE ON SCHEMA retail TO raa_wp4_portal_worker_v2;

CREATE FUNCTION retail.api_worker_portal_state_v2(p_action uuid,p_key text) RETURNS text
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,retail SET timezone='UTC' AS $fn$
DECLARE r retail.portal_approval_requests_v3%ROWTYPE; p retail.portal_publications_v2%ROWTYPE;
BEGIN
 IF p_action IS NULL OR p_key IS NULL OR p_key COLLATE "C" !~ '^[A-Za-z0-9_-]{8,128}$' THEN
  RAISE EXCEPTION 'Exact worker identity required' USING ERRCODE='22023'; END IF;
 SELECT q.* INTO r FROM retail.portal_publication_intents_v2 a JOIN retail.portal_approval_requests_v3 q USING(request_id)
  WHERE a.action_id=p_action;
 IF NOT FOUND THEN RETURN NULL; END IF;
 PERFORM retail.portal_lock_case_v2(r.case_id);
 SELECT * INTO p FROM retail.portal_publications_v2 WHERE action_id=p_action;
 IF FOUND AND p.acceptance_key IS DISTINCT FROM p_key THEN
  RAISE EXCEPTION 'Original acceptance key required' USING ERRCODE='55000'; END IF;
 RETURN jsonb_build_object('snapshot',retail.portal_request_snapshot_v3(r.request_id)::jsonb,
  'observed_at',clock_timestamp(),'acceptance_key',p.acceptance_key)::text;
END $fn$;

CREATE FUNCTION retail.api_worker_accept_portal_v2(p_action uuid,p_key text,p_case uuid,p_request_sha text,p_report_sha text)
RETURNS text LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,retail AS $fn$
DECLARE r retail.portal_approval_requests_v3%ROWTYPE;
BEGIN
 IF p_case IS NULL OR p_request_sha IS NULL OR p_report_sha IS NULL
  OR p_request_sha !~ '^[a-f0-9]{64}$' OR p_report_sha !~ '^[a-f0-9]{64}$' THEN
  RAISE EXCEPTION 'Exact worker binding required' USING ERRCODE='22023'; END IF;
 SELECT q.* INTO STRICT r FROM retail.portal_publication_intents_v2 a JOIN retail.portal_approval_requests_v3 q USING(request_id)
  WHERE a.action_id=p_action;
 PERFORM retail.portal_lock_case_v2(r.case_id);
 IF r.case_id IS DISTINCT FROM p_case OR r.payload_sha256 IS DISTINCT FROM p_request_sha OR r.report_sha256 IS DISTINCT FROM p_report_sha THEN
  RAISE EXCEPTION 'Worker binding conflict' USING ERRCODE='55000'; END IF;
 PERFORM retail.api_accept_portal_publication_v2(p_action,p_key);
 RETURN retail.api_worker_portal_state_v2(p_action,p_key);
END $fn$;
REVOKE ALL ON FUNCTION retail.api_worker_portal_state_v2(uuid,text),
 retail.api_worker_accept_portal_v2(uuid,text,uuid,text,text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION retail.api_worker_portal_state_v2(uuid,text),
 retail.api_worker_accept_portal_v2(uuid,text,uuid,text,text) TO raa_wp4_portal_worker_v2;

-- Reviewed contract DDL: 029_portal_worker_attempts.sql
CREATE TABLE retail.portal_worker_events_v1 (
 event_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 action_id uuid NOT NULL REFERENCES retail.portal_publication_intents_v2(action_id),
 event_no integer NOT NULL CHECK(event_no>0),
 acceptance_key text NOT NULL CHECK(acceptance_key COLLATE "C" ~ '^[A-Za-z0-9_-]{8,128}$'),
 attempt_id uuid NOT NULL,
 reservation_xid xid8 NOT NULL DEFAULT pg_current_xact_id(),
 attempt_no integer NOT NULL CHECK(attempt_no BETWEEN 1 AND 3),
 attempt_key text NOT NULL CHECK(attempt_key COLLATE "C" ~ '^[A-Za-z0-9_-]{8,128}$'),
 execution_id text NOT NULL CHECK(execution_id COLLATE "C" ~ '^[1-9][0-9]{0,19}$'),
 kind text NOT NULL CHECK(kind IN ('reserved','accepted','reported','reconciled','operator_reconciled')),
 outcome text NOT NULL CHECK(outcome IN ('pending','committed','uncertain','retryable','permanent','expired','superseded','exhausted')),
 state text NOT NULL CHECK(state IN ('reserved','published','unknown','retryable','dead_letter','expired','superseded','exhausted')),
 occurred_at timestamptz NOT NULL CHECK(isfinite(occurred_at)),
 lease_expires_at timestamptz NOT NULL CHECK(isfinite(lease_expires_at)),
 recovery_key text CHECK(recovery_key COLLATE "C" ~ '^[A-Za-z0-9_-]{8,128}$'),
 actor_login name NOT NULL,
 UNIQUE(action_id,event_no),
 CHECK((kind='operator_reconciled')=(recovery_key IS NOT NULL))
);
CREATE UNIQUE INDEX portal_worker_reservation_key ON retail.portal_worker_events_v1(action_id,attempt_key) WHERE kind='reserved';
CREATE UNIQUE INDEX portal_worker_attempt_number ON retail.portal_worker_events_v1(action_id,attempt_no) WHERE kind='reserved';
CREATE UNIQUE INDEX portal_worker_attempt_identity ON retail.portal_worker_events_v1(attempt_id) WHERE kind='reserved';
CREATE UNIQUE INDEX portal_worker_recovery_key ON retail.portal_worker_events_v1(action_id,recovery_key) WHERE kind='operator_reconciled';
CREATE TRIGGER immutable BEFORE UPDATE OR DELETE ON retail.portal_worker_events_v1
 FOR EACH ROW EXECUTE FUNCTION retail.reject_source_mutation();
REVOKE ALL ON retail.portal_worker_events_v1 FROM PUBLIC;

-- All state changes serialize on the existing owner/case boundary. No caller
-- timestamp, lease duration, budget, new approval or publication receipt input.
CREATE FUNCTION retail.portal_attempt_context_v1(p_action uuid,p_key text) RETURNS jsonb
LANGUAGE plpgsql VOLATILE SET search_path=pg_catalog,retail SET timezone='UTC' AS $fn$
DECLARE saved jsonb; old retail.portal_worker_events_v1%ROWTYPE;
BEGIN
 saved:=retail.api_worker_portal_state_v2(p_action,p_key)::jsonb;
 IF saved IS NULL THEN RAISE EXCEPTION 'Approved outbox required' USING ERRCODE='P0002'; END IF;
 SELECT * INTO old FROM retail.portal_worker_events_v1 WHERE action_id=p_action ORDER BY event_no DESC LIMIT 1;
 IF FOUND AND old.acceptance_key IS DISTINCT FROM p_key THEN
  RAISE EXCEPTION 'Original durable key required' USING ERRCODE='55000'; END IF;
 RETURN saved;
END $fn$;

CREATE FUNCTION retail.portal_attempt_projection_v1(p_action uuid,p_key text) RETURNS text
LANGUAGE plpgsql VOLATILE SET search_path=pg_catalog,retail SET timezone='UTC' AS $fn$
DECLARE saved jsonb; old retail.portal_worker_events_v1%ROWTYPE; result_state text; now_at timestamptz;
BEGIN
 saved:=retail.portal_attempt_context_v1(p_action,p_key); now_at:=clock_timestamp();
 SELECT * INTO old FROM retail.portal_worker_events_v1 WHERE action_id=p_action ORDER BY event_no DESC LIMIT 1;
 result_state:=CASE WHEN saved#>'{snapshot,publication}'<>'null'::jsonb THEN 'published'
  WHEN NOT (saved#>>'{snapshot,is_current}')::boolean THEN 'superseded'
  WHEN now_at>=(saved#>>'{snapshot,request,expires_at}')::timestamptz THEN 'expired'
  WHEN old.state='reserved' AND now_at>=old.lease_expires_at THEN 'unknown'
  ELSE coalesce(old.state,'pending') END;
 RETURN jsonb_build_object('contract_version','portal-worker-attempt-state-v1','worker',saved,
  'ledger',jsonb_build_object('state',result_state,'attempt_count',coalesce(old.attempt_no,0),
   'max_attempts',3,'event_no',coalesce(old.event_no,0),'attempt_id',old.attempt_id,'attempt_key',old.attempt_key,
   'execution_id',old.execution_id,'lease_expires_at',old.lease_expires_at,'last_kind',old.kind,
   'reconciliation_required',old.state IN ('reserved','unknown'),
   'acceptance_key',p_key,'observed_at',now_at))::text;
END $fn$;

CREATE FUNCTION retail.portal_attempt_result_v1(p_saved jsonb,p_attempt_no integer,p_previous text,p_outcome text) RETURNS text
LANGUAGE sql VOLATILE SET search_path=pg_catalog,retail AS $fn$
 SELECT CASE WHEN p_saved#>'{snapshot,publication}'<>'null'::jsonb THEN 'published'
  WHEN NOT (p_saved#>>'{snapshot,is_current}')::boolean THEN 'superseded'
  WHEN clock_timestamp()>=(p_saved#>>'{snapshot,request,expires_at}')::timestamptz THEN 'expired'
  WHEN p_previous='dead_letter' OR p_outcome='permanent' THEN 'dead_letter'
  WHEN p_outcome='uncertain' THEN 'unknown'
  WHEN p_attempt_no>=3 THEN 'exhausted' ELSE 'retryable' END;
$fn$;

CREATE FUNCTION retail.guard_portal_worker_event_v1() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,retail AS $fn$
DECLARE old retail.portal_worker_events_v1%ROWTYPE; saved jsonb; now_at timestamptz;
BEGIN
 saved:=retail.portal_attempt_context_v1(NEW.action_id,NEW.acceptance_key);
 SELECT * INTO old FROM retail.portal_worker_events_v1 WHERE action_id=NEW.action_id ORDER BY event_no DESC LIMIT 1;
 now_at:=clock_timestamp(); NEW.occurred_at:=now_at; NEW.actor_login:=session_user;
 IF NEW.event_no IS DISTINCT FROM coalesce(old.event_no,0)+1 THEN
  RAISE EXCEPTION 'Ordered worker event required' USING ERRCODE='55000'; END IF;
 IF NEW.kind='reserved' THEN
  IF (old.event_id IS NOT NULL AND old.state<>'retryable')
   OR NEW.attempt_no IS DISTINCT FROM coalesce(old.attempt_no,0)+1
   OR NEW.outcome<>'pending' OR NEW.state<>'reserved'
   OR saved#>'{snapshot,publication}'<>'null'::jsonb
   OR NOT (saved#>>'{snapshot,is_current}')::boolean
   OR now_at>=(saved#>>'{snapshot,request,expires_at}')::timestamptz THEN
   RAISE EXCEPTION 'Fresh bounded reservation required' USING ERRCODE='55000'; END IF;
  NEW.lease_expires_at:=least(now_at+interval '30 seconds',(saved#>>'{snapshot,request,expires_at}')::timestamptz);
  NEW.reservation_xid:=pg_current_xact_id();
 ELSE
  IF old.event_id IS NULL OR NEW.attempt_id IS DISTINCT FROM old.attempt_id
   OR NEW.attempt_no IS DISTINCT FROM old.attempt_no OR NEW.attempt_key IS DISTINCT FROM old.attempt_key
   OR NEW.reservation_xid IS DISTINCT FROM old.reservation_xid
   OR NEW.execution_id IS DISTINCT FROM old.execution_id OR NEW.lease_expires_at IS DISTINCT FROM old.lease_expires_at THEN
   RAISE EXCEPTION 'Original attempt required' USING ERRCODE='55000'; END IF;
  IF NEW.kind='accepted' THEN
   IF old.state<>'reserved' OR NEW.state<>'published' OR NEW.outcome<>'committed'
    OR saved#>'{snapshot,publication}'='null'::jsonb THEN
    RAISE EXCEPTION 'Committed acceptance event required' USING ERRCODE='55000'; END IF;
  ELSIF NEW.kind='reported' THEN
   IF old.state<>'reserved' OR NEW.outcome NOT IN ('uncertain','retryable','permanent')
    OR NEW.state IS DISTINCT FROM retail.portal_attempt_result_v1(saved,old.attempt_no,old.state,NEW.outcome) THEN
    RAISE EXCEPTION 'Bound worker outcome required' USING ERRCODE='55000'; END IF;
  ELSIF NEW.kind IN ('reconciled','operator_reconciled') THEN
   IF (NEW.kind='reconciled' AND old.state NOT IN ('reserved','unknown'))
    OR (old.state='reserved' AND now_at<old.lease_expires_at AND saved#>'{snapshot,publication}'='null'::jsonb)
    OR NEW.state IS DISTINCT FROM retail.portal_attempt_result_v1(saved,old.attempt_no,old.state,'retryable')
    OR NEW.outcome IS DISTINCT FROM (CASE NEW.state WHEN 'published' THEN 'committed'
       WHEN 'dead_letter' THEN 'permanent' WHEN 'expired' THEN 'expired' WHEN 'superseded' THEN 'superseded'
       WHEN 'exhausted' THEN 'exhausted' ELSE 'retryable' END) THEN
    RAISE EXCEPTION 'Authoritative reconciliation required' USING ERRCODE='55000'; END IF;
  END IF;
 END IF;
 RETURN NEW;
END $fn$;
CREATE TRIGGER portal_worker_event_binding BEFORE INSERT ON retail.portal_worker_events_v1
 FOR EACH ROW EXECUTE FUNCTION retail.guard_portal_worker_event_v1();

CREATE FUNCTION retail.portal_append_attempt_event_v1(p_action uuid,p_key text,p_kind text,p_outcome text,p_state text,p_recovery text DEFAULT NULL)
RETURNS void LANGUAGE plpgsql VOLATILE SET search_path=pg_catalog,retail AS $fn$
DECLARE old retail.portal_worker_events_v1%ROWTYPE;
BEGIN
 SELECT * INTO STRICT old FROM retail.portal_worker_events_v1 WHERE action_id=p_action ORDER BY event_no DESC LIMIT 1;
 INSERT INTO retail.portal_worker_events_v1(action_id,event_no,acceptance_key,attempt_id,reservation_xid,attempt_no,attempt_key,execution_id,
  kind,outcome,state,occurred_at,lease_expires_at,recovery_key,actor_login)
 VALUES(p_action,old.event_no+1,p_key,old.attempt_id,old.reservation_xid,old.attempt_no,old.attempt_key,old.execution_id,
  p_kind,p_outcome,p_state,clock_timestamp(),old.lease_expires_at,p_recovery,session_user);
END $fn$;

CREATE FUNCTION retail.api_portal_attempt_state_v1(p_action uuid,p_key text) RETURNS text
LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,retail AS $fn$
 SELECT retail.portal_attempt_projection_v1(p_action,p_key);
$fn$;

CREATE FUNCTION retail.api_reserve_portal_attempt_v1(p_action uuid,p_key text,p_case uuid,p_request_sha text,p_report_sha text,
 p_attempt_key text,p_execution text) RETURNS text
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,retail AS $fn$
DECLARE saved jsonb; old retail.portal_worker_events_v1%ROWTYPE; replay retail.portal_worker_events_v1%ROWTYPE; projected jsonb;
BEGIN
 IF p_attempt_key IS NULL OR p_attempt_key COLLATE "C" !~ '^[A-Za-z0-9_-]{8,128}$'
  OR p_execution IS NULL OR p_execution COLLATE "C" !~ '^[1-9][0-9]{0,19}$' THEN
  RAISE EXCEPTION 'Exact execution identity required' USING ERRCODE='22023'; END IF;
 saved:=retail.portal_attempt_context_v1(p_action,p_key);
 IF p_case IS NULL OR p_case::text IS DISTINCT FROM saved#>>'{snapshot,request,case_id}'
  OR p_request_sha IS DISTINCT FROM saved#>>'{snapshot,request_sha256}'
  OR p_report_sha IS DISTINCT FROM saved#>>'{snapshot,request,report_payload_sha256}' THEN
  RAISE EXCEPTION 'Exact immutable attempt binding required' USING ERRCODE='55000'; END IF;
 SELECT * INTO replay FROM retail.portal_worker_events_v1 WHERE action_id=p_action AND kind='reserved' AND attempt_key=p_attempt_key;
 IF FOUND THEN
  IF replay.execution_id IS DISTINCT FROM p_execution THEN
   RAISE EXCEPTION 'Execution key conflict' USING ERRCODE='55000'; END IF;
  RETURN retail.portal_attempt_projection_v1(p_action,p_key);
 END IF;
 projected:=retail.portal_attempt_projection_v1(p_action,p_key)::jsonb;
 IF projected#>>'{ledger,state}' NOT IN ('pending','retryable') THEN RETURN projected::text; END IF;
 SELECT * INTO old FROM retail.portal_worker_events_v1 WHERE action_id=p_action ORDER BY event_no DESC LIMIT 1;
 INSERT INTO retail.portal_worker_events_v1(action_id,event_no,acceptance_key,attempt_id,attempt_no,attempt_key,execution_id,
  kind,outcome,state,occurred_at,lease_expires_at,actor_login)
 VALUES(p_action,coalesce(old.event_no,0)+1,p_key,gen_random_uuid(),coalesce(old.attempt_no,0)+1,p_attempt_key,p_execution,
  'reserved','pending','reserved',clock_timestamp(),clock_timestamp(),session_user);
 RETURN retail.portal_attempt_projection_v1(p_action,p_key);
END $fn$;

CREATE FUNCTION retail.api_accept_portal_attempt_v1(p_action uuid,p_key text,p_attempt uuid,p_execution text) RETURNS text
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,retail AS $fn$
DECLARE saved jsonb; old retail.portal_worker_events_v1%ROWTYPE;
BEGIN
 saved:=retail.portal_attempt_context_v1(p_action,p_key);
 SELECT * INTO old FROM retail.portal_worker_events_v1 WHERE action_id=p_action ORDER BY event_no DESC LIMIT 1;
 IF p_attempt IS NULL OR p_execution IS NULL OR old.attempt_id IS DISTINCT FROM p_attempt OR old.execution_id IS DISTINCT FROM p_execution THEN
  RAISE EXCEPTION 'Exact reserved attempt required' USING ERRCODE='55000'; END IF;
 IF pg_xact_status(old.reservation_xid) IS DISTINCT FROM 'committed' THEN
  RAISE EXCEPTION 'Committed reservation required' USING ERRCODE='55000'; END IF;
 IF saved#>'{snapshot,publication}'<>'null'::jsonb THEN
  IF old.state='reserved' THEN PERFORM retail.portal_append_attempt_event_v1(p_action,p_key,'accepted','committed','published'); END IF;
  RETURN retail.portal_attempt_projection_v1(p_action,p_key);
 END IF;
 IF old.state<>'reserved' OR clock_timestamp()>=old.lease_expires_at THEN
  RAISE EXCEPTION 'Live fenced reservation required' USING ERRCODE='55000'; END IF;
 -- Unchanged acceptance trigger owns the final fresh-clock deadline sample.
 PERFORM retail.api_accept_portal_publication_v2(p_action,p_key);
 PERFORM retail.portal_append_attempt_event_v1(p_action,p_key,'accepted','committed','published');
 RETURN retail.portal_attempt_projection_v1(p_action,p_key);
END $fn$;

CREATE FUNCTION retail.api_report_portal_attempt_v1(p_action uuid,p_key text,p_attempt uuid,p_execution text,p_outcome text) RETURNS text
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,retail AS $fn$
DECLARE saved jsonb; old retail.portal_worker_events_v1%ROWTYPE; result_state text;
BEGIN
 IF p_outcome IS NULL OR p_outcome NOT IN ('uncertain','retryable','permanent') THEN
  RAISE EXCEPTION 'Fixed outcome code required' USING ERRCODE='22023'; END IF;
 saved:=retail.portal_attempt_context_v1(p_action,p_key);
 SELECT * INTO old FROM retail.portal_worker_events_v1 WHERE action_id=p_action ORDER BY event_no DESC LIMIT 1;
 IF p_attempt IS NULL OR p_execution IS NULL OR old.attempt_id IS DISTINCT FROM p_attempt OR old.execution_id IS DISTINCT FROM p_execution THEN
  RAISE EXCEPTION 'Original reporting attempt required' USING ERRCODE='55000'; END IF;
 IF old.state='published' THEN RETURN retail.portal_attempt_projection_v1(p_action,p_key); END IF;
 IF old.kind='reported' AND old.outcome=p_outcome THEN RETURN retail.portal_attempt_projection_v1(p_action,p_key); END IF;
 IF old.state<>'reserved' THEN RAISE EXCEPTION 'Unsettled attempt required' USING ERRCODE='55000'; END IF;
 result_state:=retail.portal_attempt_result_v1(saved,old.attempt_no,old.state,p_outcome);
 PERFORM retail.portal_append_attempt_event_v1(p_action,p_key,'reported',p_outcome,result_state);
 RETURN retail.portal_attempt_projection_v1(p_action,p_key);
END $fn$;

CREATE FUNCTION retail.api_reconcile_portal_attempt_v1(p_action uuid,p_key text) RETURNS text
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,retail AS $fn$
DECLARE saved jsonb; old retail.portal_worker_events_v1%ROWTYPE; result_state text; result_outcome text;
BEGIN
 saved:=retail.portal_attempt_context_v1(p_action,p_key);
 SELECT * INTO old FROM retail.portal_worker_events_v1 WHERE action_id=p_action ORDER BY event_no DESC LIMIT 1;
 IF old.event_id IS NULL OR old.state NOT IN ('reserved','unknown') THEN RETURN retail.portal_attempt_projection_v1(p_action,p_key); END IF;
 IF old.state='reserved' AND clock_timestamp()<old.lease_expires_at AND saved#>'{snapshot,publication}'='null'::jsonb THEN
  RAISE EXCEPTION 'Live reservation cannot be recovered' USING ERRCODE='55000'; END IF;
 result_state:=retail.portal_attempt_result_v1(saved,old.attempt_no,old.state,'retryable');
 result_outcome:=CASE result_state WHEN 'published' THEN 'committed' WHEN 'expired' THEN 'expired'
  WHEN 'superseded' THEN 'superseded' WHEN 'exhausted' THEN 'exhausted' ELSE 'retryable' END;
 PERFORM retail.portal_append_attempt_event_v1(p_action,p_key,'reconciled',result_outcome,result_state);
 RETURN retail.portal_attempt_projection_v1(p_action,p_key);
END $fn$;

CREATE FUNCTION retail.api_operator_reconcile_portal_v1(p_action uuid,p_key text,p_recovery text) RETURNS text
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,retail AS $fn$
DECLARE saved jsonb; old retail.portal_worker_events_v1%ROWTYPE; result_state text; result_outcome text;
BEGIN
 IF p_recovery IS NULL OR p_recovery COLLATE "C" !~ '^[A-Za-z0-9_-]{8,128}$' THEN
  RAISE EXCEPTION 'Explicit recovery key required' USING ERRCODE='22023'; END IF;
 saved:=retail.portal_attempt_context_v1(p_action,p_key);
 SELECT * INTO old FROM retail.portal_worker_events_v1 WHERE action_id=p_action ORDER BY event_no DESC LIMIT 1;
 IF old.event_id IS NULL THEN RAISE EXCEPTION 'Existing attempt required' USING ERRCODE='55000'; END IF;
 IF EXISTS(SELECT 1 FROM retail.portal_worker_events_v1 WHERE action_id=p_action AND recovery_key=p_recovery) THEN
  RETURN retail.portal_attempt_projection_v1(p_action,p_key); END IF;
 IF (SELECT count(*) FROM retail.portal_worker_events_v1 WHERE action_id=p_action AND kind='operator_reconciled')>=20 THEN
  RAISE EXCEPTION 'Bounded recovery history required' USING ERRCODE='55000'; END IF;
 IF old.state='reserved' AND clock_timestamp()<old.lease_expires_at AND saved#>'{snapshot,publication}'='null'::jsonb THEN
  RAISE EXCEPTION 'Live reservation cannot be recovered' USING ERRCODE='55000'; END IF;
 result_state:=retail.portal_attempt_result_v1(saved,old.attempt_no,old.state,'retryable');
 result_outcome:=CASE result_state WHEN 'published' THEN 'committed' WHEN 'dead_letter' THEN 'permanent'
  WHEN 'expired' THEN 'expired' WHEN 'superseded' THEN 'superseded' WHEN 'exhausted' THEN 'exhausted' ELSE 'retryable' END;
 PERFORM retail.portal_append_attempt_event_v1(p_action,p_key,'operator_reconciled',result_outcome,result_state,p_recovery);
 RETURN retail.portal_attempt_projection_v1(p_action,p_key);
END $fn$;

DO $permissions$
DECLARE fn record;
BEGIN
 FOR fn IN SELECT p.oid::regprocedure AS signature FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
  WHERE n.nspname='retail' AND p.proname IN ('portal_attempt_context_v1','portal_attempt_projection_v1',
   'portal_attempt_result_v1','guard_portal_worker_event_v1','portal_append_attempt_event_v1','api_portal_attempt_state_v1',
   'api_reserve_portal_attempt_v1','api_accept_portal_attempt_v1','api_report_portal_attempt_v1',
   'api_reconcile_portal_attempt_v1','api_operator_reconcile_portal_v1') LOOP
  EXECUTE format('REVOKE ALL ON FUNCTION %s FROM PUBLIC',fn.signature);
 END LOOP;
END $permissions$;
GRANT EXECUTE ON FUNCTION retail.api_portal_attempt_state_v1(uuid,text),
 retail.api_reserve_portal_attempt_v1(uuid,text,uuid,text,text,text,text),
 retail.api_accept_portal_attempt_v1(uuid,text,uuid,text),retail.api_report_portal_attempt_v1(uuid,text,uuid,text,text),
 retail.api_reconcile_portal_attempt_v1(uuid,text) TO raa_wp4_portal_attempt_v1;
GRANT EXECUTE ON FUNCTION retail.api_operator_reconcile_portal_v1(uuid,text,text) TO raa_wp4_portal_recovery_v1;
-- END STATIC REVIEWED CONTRACT BODIES

-- Owner-confirmed policy configuration only: no request/decision/intent/effect.
INSERT INTO retail.portal_publication_policies_v2(policy_version,reviewer_id,ttl_seconds)
 SELECT 'owner-portal-acceptance-v2',reviewer_id,86400 FROM retail.owner_credentials WHERE revoked_at IS NULL;
RESET ROLE;

CREATE TABLE raa_deployment.portal_schema_releases (
 bundle_id text PRIMARY KEY CHECK(bundle_id='wp4-rehearsal-002'),
 deployment_id uuid NOT NULL UNIQUE, checkpoint_id uuid NOT NULL,
 predecessor_id uuid NOT NULL REFERENCES raa_deployment.releases(deployment_id),
 predecessor_digest text NOT NULL CHECK(predecessor_digest ~ '^[a-f0-9]{64}$'),
 source_digest text NOT NULL CHECK(source_digest ~ '^[a-f0-9]{64}$'),
 bundle_digest text NOT NULL CHECK(bundle_digest ~ '^[a-f0-9]{64}$'),
 baseline_digest text NOT NULL CHECK(baseline_digest ~ '^[a-f0-9]{64}$'),
 base_version integer NOT NULL CHECK(base_version=20),
 target_database name NOT NULL CHECK(target_database::text ~ '^raa_wp4_populated_rehearsal_[a-f0-9]{12}$'),
 target_system text NOT NULL CHECK(target_system ~ '^[0-9]{10,20}$'),
 installed_at timestamptz NOT NULL CHECK(isfinite(installed_at)),
 admitted boolean NOT NULL DEFAULT false CHECK(admitted=false)
);
REVOKE ALL ON raa_deployment.portal_schema_releases FROM PUBLIC;
CREATE TRIGGER immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON raa_deployment.portal_schema_releases
 FOR EACH STATEMENT EXECUTE FUNCTION retail.reject_source_mutation();
INSERT INTO raa_deployment.portal_schema_releases
 SELECT 'wp4-rehearsal-002',current_setting('raa.deployment_id')::uuid,current_setting('raa.checkpoint_id')::uuid,
 current_setting('raa.predecessor_id')::uuid,current_setting('raa.predecessor_digest'),current_setting('raa.source_digest'),
 current_setting('raa.bundle_digest'),current_setting('raa.baseline_digest'),20,current_database(),
 (SELECT system_identifier::text FROM pg_control_system()),clock_timestamp(),false;
