-- Service reconciliation and retired legacy owner history. Test DB only.
DO $guard$
BEGIN
 IF current_database() !~ '^raa_wp4_dispatch_test_[a-f0-9]{12}$'
  OR NOT EXISTS(SELECT 1 FROM retail.schema_migrations WHERE version=25)
  OR EXISTS(SELECT 1 FROM retail.schema_migrations WHERE version=26) THEN
  RAISE EXCEPTION 'Fresh isolated migration-025 database required';
 END IF;
END $guard$;

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
INSERT INTO retail.schema_migrations(version,name) VALUES(26,'portal_transition_reads');
