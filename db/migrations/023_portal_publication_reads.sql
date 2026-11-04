-- Isolated owner reads only. No main deployment, role activation or old grants.
DO $guard$
BEGIN
 IF current_database() !~ '^raa_wp4_dispatch_test_[a-f0-9]{12}$'
  OR NOT EXISTS(SELECT 1 FROM retail.schema_migrations WHERE version=22)
  OR EXISTS(SELECT 1 FROM retail.schema_migrations WHERE version=23) THEN
  RAISE EXCEPTION 'Fresh isolated migration-022 database required';
 END IF;
 IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='raa_wp4_portal_read_v2') THEN
  CREATE ROLE raa_wp4_portal_read_v2 NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
 ELSIF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='raa_wp4_portal_read_v2' AND
  (rolcanlogin OR rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication OR rolbypassrls))
  OR EXISTS(SELECT 1 FROM pg_auth_members m JOIN pg_roles r ON r.oid=m.roleid WHERE r.rolname='raa_wp4_portal_read_v2') THEN
  RAISE EXCEPTION 'Unactivated scoped role required';
 END IF;
 EXECUTE format('GRANT CONNECT ON DATABASE %I TO raa_wp4_portal_read_v2',current_database());
END $guard$;
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
INSERT INTO retail.schema_migrations(version,name) VALUES(23,'portal_publication_reads');
