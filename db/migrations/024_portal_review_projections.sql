-- New-target review pages/wrapper, fresh isolated test databases only.
DO $guard$
BEGIN
 IF current_database() !~ '^raa_wp4_dispatch_test_[a-f0-9]{12}$'
  OR NOT EXISTS(SELECT 1 FROM retail.schema_migrations WHERE version=23)
  OR EXISTS(SELECT 1 FROM retail.schema_migrations WHERE version=24) THEN
  RAISE EXCEPTION 'Fresh isolated migration-023 database required';
 END IF;
END $guard$;

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
INSERT INTO retail.schema_migrations(version,name) VALUES(24,'portal_review_projections');
