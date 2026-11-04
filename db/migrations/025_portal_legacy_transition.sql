-- Explicit, one-way expired-unreviewed v2 -> portal transition. Test DB only.
DO $guard$
BEGIN
 IF current_database() !~ '^raa_wp4_dispatch_test_[a-f0-9]{12}$'
  OR NOT EXISTS(SELECT 1 FROM retail.schema_migrations WHERE version=24)
  OR EXISTS(SELECT 1 FROM retail.schema_migrations WHERE version=25) THEN
  RAISE EXCEPTION 'Fresh isolated migration-024 database required';
 END IF;
 IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='raa_wp4_portal_transition_v1') THEN
  CREATE ROLE raa_wp4_portal_transition_v1 NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
 ELSIF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='raa_wp4_portal_transition_v1' AND
  (rolcanlogin OR rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication OR rolbypassrls))
  OR EXISTS(SELECT 1 FROM pg_auth_members WHERE roleid=(SELECT oid FROM pg_roles WHERE rolname='raa_wp4_portal_transition_v1')) THEN
  RAISE EXCEPTION 'Unactivated transition role required';
 END IF;
 EXECUTE format('GRANT CONNECT ON DATABASE %I TO raa_wp4_portal_transition_v1',current_database());
 GRANT USAGE ON SCHEMA retail TO raa_wp4_portal_transition_v1;
END $guard$;

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
INSERT INTO retail.schema_migrations(version,name) VALUES(25,'portal_legacy_transition');
