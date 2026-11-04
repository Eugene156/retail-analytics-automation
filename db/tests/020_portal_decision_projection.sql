-- Live validation DB: read projections and forced-invalid decision only, fully rolled back.
\set ON_ERROR_STOP on
BEGIN;
DO $test$
DECLARE session text:=encode(sha256(convert_to(gen_random_uuid()::text,'UTF8')),'hex');
 csrf text:=encode(sha256(convert_to(gen_random_uuid()::text,'UTF8')),'hex');
 owner uuid; cid uuid:='61b10574-c842-4dae-8e8b-647f0d51ba55'; pid uuid;
 saved text; report text; projection jsonb; result text; now_at timestamptz:=clock_timestamp(); role_name text;
BEGIN
 IF NOT EXISTS(SELECT 1 FROM retail.schema_migrations WHERE version=20)
   OR EXISTS(SELECT 1 FROM retail.review_decisions_v1) THEN RAISE EXCEPTION 'Unapproved live checkpoint required'; END IF;
 saved:=retail.api_get_case_v1(cid); report:=retail.api_get_revision_v1(cid,1);
 SELECT reviewer_id INTO STRICT owner FROM retail.owner_credentials WHERE revoked_at IS NULL;
 SELECT proposal_id INTO STRICT pid FROM retail.approval_requests_v2 WHERE case_id=cid;
 INSERT INTO retail.owner_portal_sessions VALUES(session,owner,csrf,now_at,now_at+interval '1 hour',NULL);
 EXECUTE 'SET LOCAL ROLE raa_wp4_portal_api';
 projection:=retail.api_portal_request_v1(session,cid,pid)::jsonb;
 IF projection->>'decision_enabled'<>'true' OR projection->>'approved'<>'false'
   OR projection->>'published'<>'false' OR projection->'review_receipt'<>'null'::jsonb THEN
  RAISE EXCEPTION 'Current undecided portal projection failed'; END IF;
 IF retail.api_portal_case_v1(session,cid) IS DISTINCT FROM saved
   OR retail.api_portal_revision_v1(session,cid,1) IS DISTINCT FROM report THEN RAISE EXCEPTION 'Portal bytes changed'; END IF;
 -- Impossible report hash. Even a broken expiry check cannot approve M02.
 BEGIN
  PERFORM retail.api_decide_request_v1(session,csrf,cid,pid,1,repeat('0',64),
    projection->>'proposal_sha256','approve','invalid-live-binding-020');
  RAISE EXCEPTION 'Changed report hash accepted';
 EXCEPTION WHEN object_not_in_prerequisite_state THEN NULL; END;
 IF has_table_privilege(current_user,'retail.review_decisions_v1','SELECT,INSERT,UPDATE,DELETE,TRUNCATE')
   OR has_table_privilege(current_user,'retail.publication_outbox_v1','SELECT,INSERT,UPDATE,DELETE,TRUNCATE')
   OR has_function_privilege(current_user,'retail.api_issue_approval_request_v2(uuid,integer,text,text,uuid)','EXECUTE')
   OR has_schema_privilege(current_user,'retail','CREATE') THEN RAISE EXCEPTION 'Portal role too broad'; END IF;
 EXECUTE 'RESET ROLE';
 IF saved IS DISTINCT FROM retail.api_get_case_v1(cid) OR report IS DISTINCT FROM retail.api_get_revision_v1(cid,1)
   OR EXISTS(SELECT 1 FROM retail.review_decisions_v1) OR EXISTS(SELECT 1 FROM retail.publication_outbox_v1) THEN
  RAISE EXCEPTION 'Forced-invalid probe changed live case'; END IF;
 FOREACH role_name IN ARRAY ARRAY['raa_wp2_case_api','raa_wp4_reviewer_api'] LOOP
  IF has_function_privilege(role_name,'retail.api_decide_request_v1(text,text,uuid,uuid,integer,text,text,text,text)','EXECUTE') THEN
   RAISE EXCEPTION 'Service/bearer role can decide'; END IF;
 END LOOP;
 RAISE NOTICE 'PASS|portal-projections|forced-invalid-binding-denied|fixed-rights|real-M02-unchanged';
END $test$;
ROLLBACK;
