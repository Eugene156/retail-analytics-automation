-- Additive demo adapter, only in the fresh guarded publication DB of raa-p1-demo.
DO $guard$ BEGIN
 IF current_database() !~ '^raa_wp4_dispatch_test_[a-f0-9]{12}$'
 OR NOT EXISTS(SELECT 1 FROM retail.schema_migrations WHERE version=28) THEN
  RAISE EXCEPTION 'Isolated migration028 required';
 END IF;
END $guard$;

CREATE FUNCTION retail.p12_register_report(p_case uuid,p_identity jsonb,p_report text,p_hash text)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,retail AS $fn$
DECLARE old retail.report_revisions%ROWTYPE;
BEGIN
 IF p_case IS NULL OR p_identity IS NULL OR p_report IS NULL OR p_hash IS NULL
 OR p_hash !~ '^[a-f0-9]{64}$' OR octet_length(p_report)>32768
 OR encode(sha256(convert_to(p_report,'UTF8')),'hex') IS DISTINCT FROM p_hash
 OR p_report IS DISTINCT FROM p_report::jsonb::text
 OR p_report::jsonb->>'schema_version' IS DISTINCT FROM 'deterministic-comparison-report-v1'
 OR p_identity->>'source_file_sha256' IS DISTINCT FROM 'BCBE73B35F5B7BABF197FB0CB983A11F5D9FF929078D4AA53D171B1F2DF2E980'
 OR p_identity->>'contract_version' IS DISTINCT FROM 'report-request-v1' THEN
  RAISE EXCEPTION 'Invalid immutable demo report' USING ERRCODE='22023';
 END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended(p_case::text,0));
 SELECT * INTO old FROM retail.report_revisions WHERE case_id=p_case AND revision=1;
 IF FOUND THEN
  IF old.payload_text IS DISTINCT FROM p_report OR old.payload_sha256 IS DISTINCT FROM p_hash
  OR (SELECT request_identity FROM retail.report_cases WHERE case_id=p_case) IS DISTINCT FROM p_identity THEN
   RAISE EXCEPTION 'Conflicting demo report' USING ERRCODE='23505';
  END IF;
 ELSE
  INSERT INTO retail.report_cases(case_id,idempotency_key,request_identity)
    VALUES(p_case,'p12-case-'||replace(p_case::text,'-',''),p_identity);
  INSERT INTO retail.report_audit_events(case_id,event_type) VALUES(p_case,'request_received');
  INSERT INTO retail.report_revisions(case_id,revision,schema_version,payload_text,payload_sha256)
    VALUES(p_case,1,'deterministic-comparison-report-v1',p_report,p_hash);
  UPDATE retail.report_cases SET state='awaiting_approval',current_revision=1 WHERE case_id=p_case;
  INSERT INTO retail.report_audit_events(case_id,event_type,revision) VALUES(p_case,'revision_created',1);
 END IF;
 RETURN jsonb_build_object('case_id',p_case,'revision',1,'report_sha256',p_hash);
END $fn$;
REVOKE ALL ON FUNCTION retail.p12_register_report(uuid,jsonb,text,text) FROM PUBLIC;

CREATE FUNCTION retail.p12_decision_state(p_request uuid) RETURNS jsonb
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,retail AS $fn$
 SELECT jsonb_build_object('request_id',r.request_id,'case_id',r.case_id,
  'request_sha256',r.payload_sha256,'report_sha256',r.report_sha256,'decision',d.outcome,
  'action_id',a.action_id,'publication_id',p.publication_id)
 FROM retail.portal_approval_requests_v3 r
 LEFT JOIN retail.portal_review_decisions_v2 d USING(request_id)
 LEFT JOIN retail.portal_publication_intents_v2 a USING(request_id)
 LEFT JOIN retail.portal_publications_v2 p USING(action_id)
 WHERE r.request_id=p_request;
$fn$;
REVOKE ALL ON FUNCTION retail.p12_decision_state(uuid) FROM PUBLIC;
