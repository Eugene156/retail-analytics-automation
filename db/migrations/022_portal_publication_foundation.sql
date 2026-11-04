-- Staged new-target contract. Hard isolated-DB guard; never apply to main.
DO $guard$
DECLARE role_name text;
BEGIN
 IF current_database() !~ '^raa_wp4_dispatch_test_[a-f0-9]{12}$'
    OR NOT EXISTS(SELECT 1 FROM retail.schema_migrations WHERE version=21)
    OR EXISTS(SELECT 1 FROM retail.schema_migrations WHERE version=22) THEN
  RAISE EXCEPTION 'Fresh isolated migration-021 database required';
 END IF;
 FOREACH role_name IN ARRAY ARRAY['raa_wp4_portal_issue_v3','raa_wp4_portal_review_v2','raa_wp4_portal_publish_v2'] LOOP
  IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname=role_name) THEN
   EXECUTE format('CREATE ROLE %I NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS',role_name);
  ELSIF EXISTS(SELECT 1 FROM pg_roles WHERE rolname=role_name AND
    (rolcanlogin OR rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication OR rolbypassrls))
    OR EXISTS(SELECT 1 FROM pg_auth_members m JOIN pg_roles r ON r.oid=m.roleid WHERE r.rolname=role_name) THEN
   RAISE EXCEPTION 'Unactivated scoped role required';
  END IF;
  EXECUTE format('GRANT CONNECT ON DATABASE %I TO %I',current_database(),role_name);
  EXECUTE format('GRANT USAGE ON SCHEMA retail TO %I',role_name);
 END LOOP;
END $guard$;

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
INSERT INTO retail.schema_migrations(version,name) VALUES(22,'portal_publication_foundation');
