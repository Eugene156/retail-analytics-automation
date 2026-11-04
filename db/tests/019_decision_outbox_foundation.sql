-- Actual PostgreSQL contract tests; all cases, decisions and intents rollback.
\set ON_ERROR_STOP on
BEGIN;
SET LOCAL timezone='UTC';
CREATE FUNCTION pg_temp.review_fixture_v1(p_expired boolean DEFAULT false) RETURNS jsonb
LANGUAGE plpgsql AS $fixture$
DECLARE cid uuid:=gen_random_uuid(); pid uuid:=gen_random_uuid(); reviewer uuid; report text; hash text;
 session text:=encode(sha256(convert_to(gen_random_uuid()::text,'UTF8')),'hex');
 csrf text:=encode(sha256(convert_to(gen_random_uuid()::text,'UTF8')),'hex');
 created timestamptz; expires timestamptz; body text; now_at timestamptz:=statement_timestamp();
BEGIN
 SELECT reviewer_id INTO STRICT reviewer FROM retail.owner_credentials WHERE revoked_at IS NULL;
 report:=retail.api_get_revision_v1('61b10574-c842-4dae-8e8b-647f0d51ba55',1);
 IF report IS NULL THEN RAISE EXCEPTION 'Retained unapproved M02 required'; END IF;
 hash:=encode(sha256(convert_to(report,'UTF8')),'hex');
 INSERT INTO retail.report_cases(case_id,idempotency_key,request_identity)
  SELECT cid,'fixture-019-'||cid::text,request_identity FROM retail.report_cases
  WHERE case_id='61b10574-c842-4dae-8e8b-647f0d51ba55';
 INSERT INTO retail.report_audit_events(case_id,event_type) VALUES(cid,'request_received');
 INSERT INTO retail.report_revisions(case_id,revision,schema_version,payload_text,payload_sha256)
  VALUES(cid,1,'deterministic-comparison-report-v1',report,hash);
 UPDATE retail.report_cases SET state='awaiting_approval',current_revision=1,updated_at=clock_timestamp() WHERE case_id=cid;
 INSERT INTO retail.report_audit_events(case_id,event_type,revision) VALUES(cid,'revision_created',1);
 INSERT INTO retail.owner_portal_sessions VALUES(session,reviewer,csrf,now_at-interval '1 minute',
  now_at+interval '59 minutes',NULL);
 created:=CASE WHEN p_expired THEN now_at-interval '24 hours' ELSE clock_timestamp() END;
 expires:=created+interval '24 hours';
 body:=retail.approval_request_payload_v2(pid,cid,1,hash,octet_length(convert_to(report,'UTF8')),
  reviewer,created,expires,1,'fixture-019-request-'||pid::text,NULL,NULL);
 INSERT INTO retail.approval_requests_v2 VALUES(pid,cid,1,1,'fixture-019-request-'||pid::text,NULL,NULL,
  'local-publication-v1',reviewer,hash,octet_length(convert_to(report,'UTF8')),created,expires,body,
  encode(sha256(convert_to(body,'UTF8')),'hex'));
 INSERT INTO retail.approval_request_events_v2(proposal_id,occurred_at) VALUES(pid,created);
 RETURN jsonb_build_object('case',cid,'proposal',pid,'reviewer',reviewer,'session',session,'csrf',csrf,
  'report_hash',hash,'proposal_hash',encode(sha256(convert_to(body,'UTF8')),'hex'),'expires_at',expires);
END $fixture$;
CREATE FUNCTION pg_temp.decide_fixture_v1(f jsonb,choice text,key text) RETURNS text
LANGUAGE sql AS $fixture$
 SELECT retail.api_decide_request_v1(f->>'session',f->>'csrf',(f->>'case')::uuid,(f->>'proposal')::uuid,
  1,f->>'report_hash',f->>'proposal_hash',choice,key);
$fixture$;
GRANT EXECUTE ON FUNCTION pg_temp.decide_fixture_v1(jsonb,text,text) TO raa_wp4_decision_api;

DO $test$
DECLARE approved jsonb; rejected jsonb; expired jsonb; result text; saved text; command text;
 metadata text; report text; parent text; replacement text; hash text; id uuid; body text; decided timestamptz;
 initial_decisions bigint; initial_events bigint; initial_outbox bigint; i integer;
BEGIN
 metadata:=retail.api_get_case_v1('61b10574-c842-4dae-8e8b-647f0d51ba55');
 report:=retail.api_get_revision_v1('61b10574-c842-4dae-8e8b-647f0d51ba55',1);
 SELECT count(*) INTO initial_decisions FROM retail.review_decisions_v1;
 SELECT count(*) INTO initial_events FROM retail.review_decision_events_v1;
 SELECT count(*) INTO initial_outbox FROM retail.publication_outbox_v1;
 approved:=pg_temp.review_fixture_v1(); rejected:=pg_temp.review_fixture_v1(); expired:=pg_temp.review_fixture_v1(true);
 EXECUTE 'SET LOCAL ROLE raa_wp4_decision_api';
 -- Authentication and CSRF are required before an unknown object can leak.
 BEGIN
  PERFORM retail.api_decide_request_v1(repeat('0',64),repeat('0',64),gen_random_uuid(),gen_random_uuid(),1,
    repeat('0',64),repeat('0',64),'approve','fixture-019-bad-session');
  RAISE EXCEPTION 'Unknown session accepted';
 EXCEPTION WHEN insufficient_privilege THEN NULL; END;
 BEGIN
  PERFORM pg_temp.decide_fixture_v1(jsonb_set(approved,'{csrf}',to_jsonb(repeat('0',64))),'approve','fixture-019-bad-csrf');
  RAISE EXCEPTION 'Wrong CSRF accepted';
 EXCEPTION WHEN insufficient_privilege THEN NULL; END;
 BEGIN
  PERFORM pg_temp.decide_fixture_v1(jsonb_set(approved,'{proposal_hash}',to_jsonb(repeat('0',64))),'approve','fixture-019-bad-hash');
  RAISE EXCEPTION 'Changed proposal hash accepted';
 EXCEPTION WHEN object_not_in_prerequisite_state THEN NULL; END;
 BEGIN
  PERFORM pg_temp.decide_fixture_v1(jsonb_set(approved,'{report_hash}',to_jsonb(repeat('0',64))),'approve','fixture-019-bad-report');
  RAISE EXCEPTION 'Changed report hash accepted';
 EXCEPTION WHEN object_not_in_prerequisite_state THEN NULL; END;
 BEGIN
  PERFORM retail.api_decide_request_v1(approved->>'session',approved->>'csrf',(approved->>'case')::uuid,
   (approved->>'proposal')::uuid,2,approved->>'report_hash',approved->>'proposal_hash','approve','fixture-019-bad-version');
  RAISE EXCEPTION 'Wrong revision accepted';
 EXCEPTION WHEN invalid_parameter_value THEN NULL; END;
 BEGIN
  PERFORM pg_temp.decide_fixture_v1(approved,'expire','fixture-019-early-expiry');
  RAISE EXCEPTION 'Early expiry accepted';
 EXCEPTION WHEN object_not_in_prerequisite_state THEN NULL; END;
 FOREACH command IN ARRAY ARRAY['approve','reject'] LOOP
  BEGIN
   PERFORM pg_temp.decide_fixture_v1(expired,command,'fixture-019-late-'||command);
   RAISE EXCEPTION 'Late review accepted';
  EXCEPTION WHEN object_not_in_prerequisite_state THEN NULL; END;
 END LOOP;
 saved:=pg_temp.decide_fixture_v1(approved,'approve','fixture-019-approve');
 IF saved::jsonb#>>'{decision,outcome}'<>'approved' OR saved::jsonb#>>'{outbox,state}'<>'pending'
   OR saved::jsonb#>>'{outbox,content_sha256}'<>approved->>'report_hash'
   OR saved::jsonb#>>'{outbox,relative_path}'<>'reports/approved/v1/'||(approved->>'case')||'/revision-1.json'
   OR saved::jsonb->>'published'<>'false' OR saved::jsonb->>'dispatch_enabled'<>'false'
   OR encode(sha256(convert_to(saved::jsonb->>'canonical_payload_text','UTF8')),'hex')<>saved::jsonb->>'decision_sha256'
   OR saved::jsonb#>>'{audit_event,event_type}'<>'review_approved' THEN RAISE EXCEPTION 'Approval bundle failed'; END IF;
 FOR i IN 1..10 LOOP
  result:=pg_temp.decide_fixture_v1(approved,'approve','fixture-019-approve');
  IF result IS DISTINCT FROM saved THEN RAISE EXCEPTION 'Replay changed decision/action'; END IF;
 END LOOP;
 IF retail.api_decision_snapshot_v1(approved->>'session',(approved->>'case')::uuid,(approved->>'proposal')::uuid)
   IS DISTINCT FROM saved THEN RAISE EXCEPTION 'Authorized read differs'; END IF;
 BEGIN
  PERFORM pg_temp.decide_fixture_v1(approved,'reject','fixture-019-approve');
  RAISE EXCEPTION 'Changed key outcome accepted';
 EXCEPTION WHEN object_not_in_prerequisite_state THEN NULL; END;
 BEGIN
  PERFORM pg_temp.decide_fixture_v1(approved,'approve','fixture-019-new-approve-key');
  RAISE EXCEPTION 'Second decision key accepted';
 EXCEPTION WHEN object_not_in_prerequisite_state THEN NULL; END;
 result:=pg_temp.decide_fixture_v1(rejected,'reject','fixture-019-reject');
 IF result::jsonb#>>'{decision,outcome}'<>'rejected' OR result::jsonb->'outbox'<>'null'::jsonb THEN
  RAISE EXCEPTION 'Reject queued action'; END IF;
 result:=pg_temp.decide_fixture_v1(expired,'expire','fixture-019-expire');
 IF result::jsonb#>>'{decision,outcome}'<>'expired' OR result::jsonb->'outbox'<>'null'::jsonb THEN
  RAISE EXCEPTION 'Expiry queued action'; END IF;
 EXECUTE 'RESET ROLE';
 -- Force deferred bundle checks rather than assuming ROLLBACK exercised them.
 EXECUTE 'SET CONSTRAINTS retail.review_decision_complete IMMEDIATE';
 IF (SELECT count(*) FROM retail.review_decisions_v1)<>initial_decisions+3
   OR (SELECT count(*) FROM retail.review_decision_events_v1)<>initial_events+3
   OR (SELECT count(*) FROM retail.publication_outbox_v1)<>initial_outbox+1 THEN RAISE EXCEPTION 'Duplicate bundle'; END IF;
 IF NOT EXISTS(SELECT 1 FROM retail.publication_outbox_v1 a JOIN retail.report_revisions r
    ON (a.case_id,a.report_revision)=(r.case_id,r.revision) WHERE a.case_id=(approved->>'case')::uuid
    AND a.content_text=r.payload_text AND a.content_bytes=octet_length(convert_to(r.payload_text,'UTF8'))) THEN
  RAISE EXCEPTION 'Exact content changed'; END IF;
 -- Expiry decisions permit an explicit new request, never in-place renewal.
 replacement:=retail.api_issue_approval_request_v2((expired->>'case')::uuid,1,expired->>'report_hash',
    'fixture-019-expired-successor',(expired->>'proposal')::uuid);
 IF replacement::jsonb#>>'{proposal,generation}'<>'2' THEN RAISE EXCEPTION 'Expired successor failed'; END IF;
 EXECUTE 'SET LOCAL ROLE raa_wp4_decision_api';
 BEGIN
  PERFORM pg_temp.decide_fixture_v1(expired,'approve','fixture-019-superseded');
  RAISE EXCEPTION 'Superseded request accepted';
 EXCEPTION WHEN object_not_in_prerequisite_state THEN NULL; END;
 EXECUTE 'RESET ROLE';
 FOREACH command IN ARRAY ARRAY[
  'UPDATE retail.review_decisions_v1 SET outcome=''rejected''',
  'DELETE FROM retail.review_decision_events_v1','TRUNCATE retail.publication_outbox_v1',
  'UPDATE retail.publication_outbox_v1 SET relative_path=''../outside.json'''] LOOP
  BEGIN EXECUTE command; RAISE EXCEPTION 'Immutable history changed';
  EXCEPTION WHEN raise_exception THEN IF SQLERRM='Immutable history changed' THEN RAISE; END IF; END;
 END LOOP;
 -- Privileged direct writes also need a complete bundle at constraint check.
 parent:=pg_temp.review_fixture_v1()::text;
 BEGIN
  id:=gen_random_uuid(); decided:=clock_timestamp();
  body:=retail.decision_payload_v1(id,(parent::jsonb->>'case')::uuid,(parent::jsonb->>'proposal')::uuid,1,
   parent::jsonb->>'proposal_hash',parent::jsonb->>'report_hash',(parent::jsonb->>'reviewer')::uuid,
   'fixture-019-incomplete','approved',decided,(parent::jsonb->>'expires_at')::timestamptz);
  INSERT INTO retail.review_decisions_v1 VALUES(id,(parent::jsonb->>'case')::uuid,(parent::jsonb->>'proposal')::uuid,
   1,parent::jsonb->>'proposal_hash',parent::jsonb->>'report_hash',(parent::jsonb->>'reviewer')::uuid,
   parent::jsonb->>'session','fixture-019-incomplete','approved',decided,(parent::jsonb->>'expires_at')::timestamptz,
   body,encode(sha256(convert_to(body,'UTF8')),'hex'));
  RAISE EXCEPTION 'Incomplete bundle accepted';
 EXCEPTION WHEN raise_exception THEN
  IF SQLERRM<>'Incomplete decision event/outbox bundle' THEN RAISE; END IF;
 END;
 -- Owner revocation blocks even a same-key historical replay.
 BEGIN
  UPDATE retail.owner_credentials SET revoked_at=clock_timestamp() WHERE reviewer_id=(approved->>'reviewer')::uuid;
  EXECUTE 'SET LOCAL ROLE raa_wp4_decision_api';
  PERFORM pg_temp.decide_fixture_v1(approved,'approve','fixture-019-approve');
  RAISE EXCEPTION 'Revoked owner replay accepted';
 EXCEPTION WHEN insufficient_privilege THEN NULL; END;
 EXECUTE 'RESET ROLE';
 BEGIN
  UPDATE retail.owner_portal_sessions SET revoked_at=clock_timestamp() WHERE session_sha256=approved->>'session';
  EXECUTE 'SET LOCAL ROLE raa_wp4_decision_api';
  PERFORM pg_temp.decide_fixture_v1(approved,'approve','fixture-019-approve');
  RAISE EXCEPTION 'Logged-out session replay accepted';
 EXCEPTION WHEN insufficient_privilege THEN NULL; END;
 EXECUTE 'RESET ROLE';
 IF metadata IS DISTINCT FROM retail.api_get_case_v1('61b10574-c842-4dae-8e8b-647f0d51ba55')
   OR report IS DISTINCT FROM retail.api_get_revision_v1('61b10574-c842-4dae-8e8b-647f0d51ba55',1) THEN
  RAISE EXCEPTION 'Real M02 changed'; END IF;
 RAISE NOTICE 'PASS|decision-sql|approve-one-exact-intent|reject-expire-no-intent|ten-replays|binding-csrf-revocation|deferred-completeness|immutability|real-M02-unchanged';
END $test$;
SET CONSTRAINTS retail.review_decision_complete DEFERRED;

CREATE FUNCTION pg_temp.fail_review_bundle_v1() RETURNS trigger LANGUAGE plpgsql AS $fault$
BEGIN
 IF (TG_TABLE_NAME='review_decision_events_v1' AND current_setting('raa.test_fault',true)='audit')
   OR (TG_TABLE_NAME='publication_outbox_v1' AND current_setting('raa.test_fault',true)='outbox') THEN
  RAISE EXCEPTION 'Injected decision bundle failure';
 END IF;
 RETURN NEW;
END $fault$;
CREATE TRIGGER wp4_019_audit_fault BEFORE INSERT ON retail.review_decision_events_v1
 FOR EACH ROW EXECUTE FUNCTION pg_temp.fail_review_bundle_v1();
CREATE TRIGGER wp4_019_outbox_fault BEFORE INSERT ON retail.publication_outbox_v1
 FOR EACH ROW EXECUTE FUNCTION pg_temp.fail_review_bundle_v1();
DO $atomicity$
DECLARE f jsonb; fault text; before_case text;
BEGIN
 FOREACH fault IN ARRAY ARRAY['audit','outbox'] LOOP
  f:=pg_temp.review_fixture_v1(); before_case:=retail.api_get_case_v1((f->>'case')::uuid);
  PERFORM set_config('raa.test_fault',fault,true);
  BEGIN
   EXECUTE 'SET LOCAL ROLE raa_wp4_decision_api';
   PERFORM pg_temp.decide_fixture_v1(f,'approve','fixture-019-atomic-'||fault);
   RAISE EXCEPTION 'Fault not fired';
  EXCEPTION WHEN raise_exception THEN
   IF SQLERRM<>'Injected decision bundle failure' THEN RAISE; END IF;
  END;
  EXECUTE 'RESET ROLE';
  IF EXISTS(SELECT 1 FROM retail.review_decisions_v1 WHERE case_id=(f->>'case')::uuid)
    OR EXISTS(SELECT 1 FROM retail.publication_outbox_v1 WHERE case_id=(f->>'case')::uuid)
    OR EXISTS(SELECT 1 FROM retail.review_decision_events_v1 e JOIN retail.review_decisions_v1 d USING(decision_id)
      WHERE d.case_id=(f->>'case')::uuid)
    OR before_case IS DISTINCT FROM retail.api_get_case_v1((f->>'case')::uuid) THEN
   RAISE EXCEPTION 'Partial bundle after fault';
  END IF;
 END LOOP;
 PERFORM set_config('raa.test_fault','none',true);
 RAISE NOTICE 'PASS|decision-atomicity|actual-audit-and-outbox-insert-faults|no-partial-decision-event-intent';
END $atomicity$;

DO $tamper$
DECLARE f jsonb; expiry_fixture jsonb; good retail.review_decisions_v1%ROWTYPE;
 bad retail.review_decisions_v1%ROWTYPE; good_action retail.publication_outbox_v1%ROWTYPE;
 bad_action retail.publication_outbox_v1%ROWTYPE; mode integer; result text; rejected boolean;
BEGIN
 f:=pg_temp.review_fixture_v1();
 -- A successful full bundle is rolled back first, freeing every unique key.
 BEGIN
  PERFORM pg_temp.decide_fixture_v1(f,'approve','fixture-019-tamper-control');
  SELECT * INTO STRICT good FROM retail.review_decisions_v1 WHERE case_id=(f->>'case')::uuid;
  SELECT * INTO STRICT good_action FROM retail.publication_outbox_v1 WHERE case_id=(f->>'case')::uuid;
  RAISE EXCEPTION 'Control rollback';
 EXCEPTION WHEN raise_exception THEN IF SQLERRM<>'Control rollback' THEN RAISE; END IF; END;
 FOR mode IN 1..14 LOOP
  bad:=good;
  CASE mode
   WHEN 1 THEN bad.proposal_sha256:=repeat('0',64);
   WHEN 2 THEN bad.report_payload_sha256:=repeat('0',64);
   WHEN 3 THEN bad.report_revision:=2;
   WHEN 4 THEN bad.reviewer_id:=gen_random_uuid();
   WHEN 5 THEN bad.session_sha256:=repeat('0',64);
   WHEN 6 THEN bad.case_id:=gen_random_uuid();
   WHEN 7 THEN bad.authorization_expires_at:=good.authorization_expires_at+interval '1 second';
   WHEN 8 THEN bad.decided_at:=clock_timestamp()+interval '1 hour';
   WHEN 9 THEN bad.outcome:='expired';
   WHEN 10 THEN bad.payload_text:=jsonb_set(good.payload_text::jsonb,'{outcome}','"rejected"')::text;
   WHEN 11 THEN bad.payload_sha256:=repeat('0',64);
   WHEN 12 THEN bad.decision_key:=NULL;
   WHEN 13 THEN bad.payload_text:=NULL;
   WHEN 14 THEN bad.outcome:=NULL;
  END CASE;
  rejected:=false;
  BEGIN INSERT INTO retail.review_decisions_v1 SELECT (bad).*;
  EXCEPTION WHEN integrity_constraint_violation OR invalid_parameter_value OR raise_exception THEN rejected:=true; END;
  IF NOT rejected THEN RAISE EXCEPTION 'Decision tamper accepted: %',mode; END IF;
 END LOOP;
 -- Insert the valid decision/event, then test each intent without collisions.
 INSERT INTO retail.review_decisions_v1 SELECT (good).*;
 INSERT INTO retail.review_decision_events_v1(decision_id,event_type,reviewer_id,occurred_at)
  VALUES(good.decision_id,'review_approved',good.reviewer_id,good.decided_at);
 FOR mode IN 1..12 LOOP
  bad_action:=good_action;
  CASE mode
   WHEN 1 THEN bad_action.relative_path:='../outside.json';
   WHEN 2 THEN bad_action.target_id:='caller-target';
   WHEN 3 THEN bad_action.content_text:=good_action.content_text||' ';
   WHEN 4 THEN bad_action.content_sha256:=repeat('0',64);
   WHEN 5 THEN bad_action.content_bytes:=good_action.content_bytes+1;
   WHEN 6 THEN bad_action.proposal_sha256:=repeat('0',64);
   WHEN 7 THEN bad_action.action_key:='changed-action-key';
   WHEN 8 THEN bad_action.authorization_expires_at:=good_action.authorization_expires_at+interval '1 hour';
   WHEN 9 THEN bad_action.action_payload_text:=jsonb_set(good_action.action_payload_text::jsonb,'{target,relative_path}','"../outside.json"')::text;
   WHEN 10 THEN bad_action.created_at:=good_action.created_at+interval '1 second';
   WHEN 11 THEN bad_action.report_revision:=2;
   WHEN 12 THEN bad_action.state:='succeeded';
  END CASE;
  rejected:=false;
  BEGIN INSERT INTO retail.publication_outbox_v1 SELECT (bad_action).*;
  EXCEPTION WHEN integrity_constraint_violation OR raise_exception THEN rejected:=true; END;
  IF NOT rejected THEN RAISE EXCEPTION 'Intent tamper accepted: %',mode; END IF;
 END LOOP;
 INSERT INTO retail.publication_outbox_v1 SELECT (good_action).*;
 -- Exact approval expiry equality cannot pass even a privileged candidate.
 expiry_fixture:=pg_temp.review_fixture_v1(true);
 bad:=good; bad.decision_id:=gen_random_uuid(); bad.case_id:=(expiry_fixture->>'case')::uuid;
 bad.proposal_id:=(expiry_fixture->>'proposal')::uuid; bad.proposal_sha256:=expiry_fixture->>'proposal_hash';
 bad.session_sha256:=expiry_fixture->>'session'; bad.decided_at:=(expiry_fixture->>'expires_at')::timestamptz;
 bad.authorization_expires_at:=bad.decided_at; bad.decision_key:='fixture-019-boundary';
 bad.payload_text:=retail.decision_payload_v1(bad.decision_id,bad.case_id,bad.proposal_id,1,bad.proposal_sha256,
  bad.report_payload_sha256,bad.reviewer_id,bad.decision_key,'approved',bad.decided_at,bad.authorization_expires_at);
 bad.payload_sha256:=encode(sha256(convert_to(bad.payload_text,'UTF8')),'hex');
 BEGIN INSERT INTO retail.review_decisions_v1 SELECT (bad).*; RAISE EXCEPTION 'Expiry equality accepted';
 EXCEPTION WHEN invalid_parameter_value THEN NULL; END;
 -- A valid historical approval before that boundary remains a replay only.
 bad.decided_at:=bad.decided_at-interval '1 second';
 bad.payload_text:=retail.decision_payload_v1(bad.decision_id,bad.case_id,bad.proposal_id,1,bad.proposal_sha256,
  bad.report_payload_sha256,bad.reviewer_id,bad.decision_key,'approved',bad.decided_at,bad.authorization_expires_at);
 bad.payload_sha256:=encode(sha256(convert_to(bad.payload_text,'UTF8')),'hex');
 INSERT INTO retail.review_decisions_v1 SELECT (bad).*;
 INSERT INTO retail.review_decision_events_v1(decision_id,event_type,reviewer_id,occurred_at)
  VALUES(bad.decision_id,'review_approved',bad.reviewer_id,bad.decided_at);
 good_action.action_id:=gen_random_uuid(); good_action.action_key:='publish-local-v1:'||bad.proposal_id::text;
 good_action.decision_id:=bad.decision_id; good_action.proposal_id:=bad.proposal_id; good_action.case_id:=bad.case_id;
 good_action.relative_path:='reports/approved/v1/'||bad.case_id::text||'/revision-1.json';
 good_action.proposal_sha256:=bad.proposal_sha256; good_action.created_at:=bad.decided_at;
 good_action.authorization_expires_at:=bad.authorization_expires_at;
 good_action.action_payload_text:=(SELECT (payload_text::jsonb->'action')::text FROM retail.approval_requests_v2 WHERE proposal_id=bad.proposal_id);
 good_action.action_payload_sha256:=encode(sha256(convert_to(good_action.action_payload_text,'UTF8')),'hex');
 INSERT INTO retail.publication_outbox_v1 SELECT (good_action).*;
 result:=pg_temp.decide_fixture_v1(expiry_fixture,'approve','fixture-019-boundary');
 IF result::jsonb#>>'{decision,decision_id}'<>bad.decision_id::text
   OR (result::jsonb#>>'{outbox,authorization_expires_at}')::timestamptz<>bad.authorization_expires_at THEN
  RAISE EXCEPTION 'Historical replay renewed authorization'; END IF;
 BEGIN
  PERFORM retail.api_issue_approval_request_v2(bad.case_id,1,bad.report_payload_sha256,
   'fixture-019-no-terminal-successor',bad.proposal_id);
  RAISE EXCEPTION 'Terminal successor accepted';
 EXCEPTION WHEN object_not_in_prerequisite_state THEN NULL; END;
 EXECUTE 'SET CONSTRAINTS retail.review_decision_complete IMMEDIATE';
 RAISE NOTICE 'PASS|26-noncollision-tamper-denials|exact-exclusive-expiry|historical-replay-no-renewal|terminal-successor-denied';
END $tamper$;
ROLLBACK;

BEGIN;
SET LOCAL ROLE raa_wp4_decision_api;
DO $permissions$ BEGIN
 IF NOT has_function_privilege(current_user,'retail.api_decide_request_v1(text,text,uuid,uuid,integer,text,text,text,text)','EXECUTE')
   OR has_table_privilege(current_user,'retail.review_decisions_v1','SELECT,INSERT,UPDATE,DELETE,TRUNCATE')
   OR has_table_privilege(current_user,'retail.publication_outbox_v1','SELECT,INSERT,UPDATE,DELETE,TRUNCATE')
   OR has_function_privilege(current_user,'retail.api_issue_approval_request_v2(uuid,integer,text,text,uuid)','EXECUTE')
   OR has_function_privilege(current_user,'retail.api_portal_login_v1(text,text,text,text)','EXECUTE')
   OR has_schema_privilege(current_user,'retail','CREATE') THEN RAISE EXCEPTION 'Decision role too broad'; END IF;
 BEGIN PERFORM 1 FROM retail.review_decisions_v1; RAISE EXCEPTION 'Direct decision read accepted';
 EXCEPTION WHEN insufficient_privilege THEN NULL; END;
END $permissions$;
ROLLBACK;
DO $deployment$ DECLARE role_name text; BEGIN
 IF (SELECT rolcanlogin FROM pg_roles WHERE rolname='raa_wp4_decision_api') THEN RAISE EXCEPTION 'Staged role login enabled'; END IF;
 FOREACH role_name IN ARRAY ARRAY['raa_wp2_case_api','raa_wp4_reviewer_api'] LOOP
  IF has_function_privilege(role_name,'retail.api_decide_request_v1(text,text,uuid,uuid,integer,text,text,text,text)','EXECUTE') THEN
   RAISE EXCEPTION 'Existing runtime can decide'; END IF;
 END LOOP;
 IF has_function_privilege('raa_wp4_portal_api',
      'retail.api_decide_request_v1(text,text,uuid,uuid,integer,text,text,text,text)','EXECUTE')
   IS DISTINCT FROM EXISTS(SELECT 1 FROM retail.schema_migrations WHERE version=20) THEN
  RAISE EXCEPTION 'Portal decision grant disagrees with migration phase';
 END IF;
END $deployment$;
SELECT 'PASS|decision-role|two-functions-only|NOLOGIN|service-bearer-no-decision-grant|portal-grant-matches-phase|rollback';
