-- Fixed worker state/acceptance boundary, isolated test databases only.
DO $guard$
BEGIN
 IF current_database() !~ '^raa_wp4_dispatch_test_[a-f0-9]{12}$'
  OR NOT EXISTS(SELECT 1 FROM retail.schema_migrations WHERE version=27)
  OR EXISTS(SELECT 1 FROM retail.schema_migrations WHERE version=28) THEN
  RAISE EXCEPTION 'Fresh isolated migration-027 database required'; END IF;
 IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='raa_wp4_portal_worker_v2') THEN
  CREATE ROLE raa_wp4_portal_worker_v2 NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
 ELSIF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='raa_wp4_portal_worker_v2' AND
  (rolcanlogin OR rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication OR rolbypassrls))
  OR EXISTS(SELECT 1 FROM pg_auth_members m JOIN pg_roles r ON r.oid=m.roleid WHERE r.rolname='raa_wp4_portal_worker_v2') THEN
  RAISE EXCEPTION 'Unactivated scoped worker role required'; END IF;
 EXECUTE format('GRANT CONNECT ON DATABASE %I TO raa_wp4_portal_worker_v2',current_database());
END $guard$;
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
INSERT INTO retail.schema_migrations(version,name) VALUES(28,'portal_worker_boundary');
