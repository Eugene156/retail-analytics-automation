-- Derived lifecycle: immutable review ledger is authoritative; draft storage stays unchanged.
DO $guard$ BEGIN
 IF current_database()<>'raa_wp2_validation'
   OR NOT EXISTS(SELECT 1 FROM retail.schema_migrations WHERE version=19)
   OR EXISTS(SELECT 1 FROM retail.schema_migrations WHERE version=20)
   OR EXISTS(SELECT 1 FROM retail.review_decisions_v1) THEN
  RAISE EXCEPTION 'Unactivated migration 019 validation database required';
 END IF;
END $guard$;

CREATE OR REPLACE FUNCTION retail.report_case_metadata_v1(p_case_id uuid) RETURNS text
LANGUAGE sql STABLE SET search_path=pg_catalog,retail SET timezone='UTC' AS $function$
 SELECT (jsonb_build_object('case_id',c.case_id,'state',coalesce(d.outcome,c.state),
   'revision',c.current_revision,'request',c.request_identity,'created_at',c.created_at,
   'updated_at',coalesce(d.decided_at,c.updated_at),'payload_sha256',r.payload_sha256,
   'schema_version',r.schema_version,'approved',coalesce(d.outcome='approved',false),'published',false,
   'audit_events',(SELECT jsonb_agg(jsonb_build_object('event_id',a.event_id,'event_type',a.event_type,
     'revision',a.revision,'occurred_at',a.occurred_at,'actor',a.actor) ORDER BY a.occurred_at,a.event_type)
     FROM retail.report_audit_events a WHERE a.case_id=c.case_id))
   || CASE WHEN d.decision_id IS NULL THEN '{}'::jsonb ELSE jsonb_build_object(
     'review_receipt',retail.decision_snapshot_v1(d.case_id,d.proposal_id)::jsonb) END)::text
 FROM retail.report_cases c LEFT JOIN retail.report_revisions r
   ON (r.case_id,r.revision)=(c.case_id,c.current_revision)
 LEFT JOIN retail.review_decisions_v1 d ON d.case_id=c.case_id AND d.report_revision=c.current_revision
   AND d.outcome IN ('approved','rejected')
 WHERE c.case_id=p_case_id AND c.requester='local-service-v1';
$function$;

CREATE OR REPLACE FUNCTION retail.api_get_approval_request_v2(p_case uuid,p_id uuid) RETURNS text
LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,retail SET timezone='UTC' AS $function$
 SELECT jsonb_build_object('proposal',r.payload_text::jsonb,'canonical_payload_text',r.payload_text,
   'proposal_sha256',r.payload_sha256,
   'review_status',coalesce(d.outcome,CASE WHEN EXISTS(SELECT 1 FROM retail.approval_requests_v2 n
     WHERE n.predecessor_proposal_id=r.proposal_id) THEN 'superseded'
     WHEN statement_timestamp()>=r.expires_at THEN 'expired' ELSE 'pending_review' END),
   'is_current',NOT EXISTS(SELECT 1 FROM retail.approval_requests_v2 n WHERE n.predecessor_proposal_id=r.proposal_id),
   'decision_enabled',false,'approved',coalesce(d.outcome='approved',false),'published',false,
   'review_receipt',retail.decision_snapshot_v1(r.case_id,r.proposal_id)::jsonb,
   'creation_event',jsonb_build_object('event_id',e.event_id,'event_type',e.event_type,
     'occurred_at',e.occurred_at,'actor',e.actor))::text
 FROM retail.approval_requests_v2 r JOIN retail.approval_request_events_v2 e USING(proposal_id)
 JOIN retail.report_cases c ON c.case_id=r.case_id AND c.requester='local-service-v1'
   AND c.state='awaiting_approval' AND c.current_revision=r.report_revision
 LEFT JOIN retail.review_decisions_v1 d ON d.proposal_id=r.proposal_id
 WHERE r.case_id=p_case AND r.proposal_id=p_id;
$function$;

CREATE OR REPLACE FUNCTION retail.api_portal_requests_v1(p_session text) RETURNS text
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,retail SET timezone='UTC' AS $function$
DECLARE identity uuid; result text;
BEGIN
 identity:=retail.api_portal_identity_v1(p_session);
 IF identity IS NULL THEN RAISE EXCEPTION 'Unauthorized' USING ERRCODE='42501'; END IF;
 SELECT coalesce(jsonb_agg(jsonb_build_object('case_id',r.case_id,'proposal_id',r.proposal_id,
   'created_at',r.created_at,'expires_at',r.expires_at,'generation',r.generation,
   'review_status',coalesce(d.outcome,CASE WHEN statement_timestamp()>=r.expires_at
     THEN 'expired' ELSE 'pending_review' END)) ORDER BY r.created_at DESC),'[]'::jsonb)::text INTO result
 FROM (SELECT r.* FROM retail.approval_requests_v2 r JOIN retail.report_cases c USING(case_id)
   WHERE r.reviewer_id=identity AND c.state='awaiting_approval' AND c.current_revision=r.report_revision
     AND NOT EXISTS(SELECT 1 FROM retail.approval_requests_v2 n WHERE n.predecessor_proposal_id=r.proposal_id)
   ORDER BY r.created_at DESC LIMIT 20) r LEFT JOIN retail.review_decisions_v1 d USING(proposal_id);
 RETURN result;
END $function$;

CREATE OR REPLACE FUNCTION retail.api_portal_request_v1(p_session text,p_case uuid,p_id uuid) RETURNS text
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,retail AS $function$
DECLARE identity uuid; result jsonb;
BEGIN
 identity:=retail.api_portal_identity_v1(p_session);
 IF identity IS NULL THEN RAISE EXCEPTION 'Unauthorized' USING ERRCODE='42501'; END IF;
 result:=retail.api_get_approval_request_v2(p_case,p_id)::jsonb;
 IF result IS NOT NULL AND (result#>>'{proposal,reviewer_id}')::uuid IS DISTINCT FROM identity THEN
  RAISE EXCEPTION 'Unauthorized' USING ERRCODE='42501';
 END IF;
 IF result IS NOT NULL THEN
  result:=result||jsonb_build_object('decision_enabled',(result->>'is_current')::boolean
    AND result->'review_receipt'='null'::jsonb
    AND NOT EXISTS(SELECT 1 FROM retail.review_decisions_v1 WHERE case_id=p_case
      AND outcome IN ('approved','rejected')));
 END IF;
 RETURN result::text;
END $function$;

-- Portal backend gains only the same two fixed session/CSRF-bound operations.
-- No service/bearer grant, role membership, arbitrary SQL or new secret.
GRANT EXECUTE ON FUNCTION retail.api_decide_request_v1(text,text,uuid,uuid,integer,text,text,text,text),
 retail.api_decision_snapshot_v1(text,uuid,uuid) TO raa_wp4_portal_api;
INSERT INTO retail.schema_migrations(version,name) VALUES(20,'portal_decision_projection');
