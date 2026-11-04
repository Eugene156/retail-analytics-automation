-- Shared absolute-hour authentication, fixed new-target wrappers. Test DB only.
DO $guard$
BEGIN
 IF current_database() !~ '^raa_wp4_dispatch_test_[a-f0-9]{12}$'
  OR NOT EXISTS(SELECT 1 FROM retail.schema_migrations WHERE version=26)
  OR EXISTS(SELECT 1 FROM retail.schema_migrations WHERE version=27) THEN
  RAISE EXCEPTION 'Fresh isolated migration-026 database required';
 END IF;
 IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='raa_wp4_portal_auth_v2') THEN
  CREATE ROLE raa_wp4_portal_auth_v2 NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
 ELSIF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='raa_wp4_portal_auth_v2' AND
  (rolcanlogin OR rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication OR rolbypassrls))
  OR EXISTS(SELECT 1 FROM pg_auth_members m JOIN pg_roles r ON r.oid=m.roleid WHERE r.rolname='raa_wp4_portal_auth_v2') THEN
  RAISE EXCEPTION 'Unactivated scoped role required';
 END IF;
 EXECUTE format('GRANT CONNECT ON DATABASE %I TO raa_wp4_portal_auth_v2',current_database());
END $guard$;
GRANT USAGE ON SCHEMA retail TO raa_wp4_portal_auth_v2;

CREATE FUNCTION retail.api_portal_auth_identity_v2(p_session text) RETURNS uuid
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,retail AS $fn$
DECLARE identity uuid;
BEGIN
 identity:=retail.portal_owner_identity_v2(p_session);
 IF NOT EXISTS(SELECT 1 FROM retail.portal_publication_policies_v2
  WHERE policy_version='owner-portal-acceptance-v2' AND ttl_seconds=86400 AND reviewer_id=identity) THEN
  RAISE EXCEPTION 'Unauthorized' USING ERRCODE='42501'; END IF;
 RETURN identity;
END $fn$;

CREATE FUNCTION retail.api_portal_auth_login_v2(p_owner text,p_session text,p_csrf text,p_old text) RETURNS text
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,retail SET timezone='UTC' AS $fn$
DECLARE identity uuid; s retail.owner_portal_sessions%ROWTYPE;
BEGIN
 -- Existing owner UPDATE lock serializes rotation/cap/revocation. Validate the
 -- separate new-target policy before invoking the unchanged auth-state function.
 SELECT c.reviewer_id INTO identity FROM retail.owner_credentials c
 JOIN retail.portal_publication_policies_v2 p ON p.reviewer_id=c.reviewer_id
  AND p.policy_version='owner-portal-acceptance-v2' AND p.ttl_seconds=86400
 WHERE c.token_sha256=p_owner AND c.revoked_at IS NULL FOR UPDATE OF c NOWAIT;
 IF identity IS NULL THEN RAISE EXCEPTION 'Unauthorized' USING ERRCODE='42501'; END IF;
 IF retail.api_portal_login_v1(p_owner,p_session,p_csrf,p_old) IS DISTINCT FROM identity THEN
  RAISE EXCEPTION 'Unauthorized' USING ERRCODE='42501'; END IF;
 SELECT * INTO STRICT s FROM retail.owner_portal_sessions WHERE session_sha256=p_session;
 RETURN jsonb_build_object('reviewer_id',identity,'created_at',s.created_at,'expires_at',s.expires_at)::text;
END $fn$;

CREATE FUNCTION retail.api_portal_auth_logout_v2(p_session text,p_csrf text) RETURNS boolean
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,retail AS $fn$
BEGIN
 -- Fresh clock and owner/session SHARE locks through the logout transaction.
 PERFORM retail.api_portal_auth_identity_v2(p_session);
 RETURN retail.api_portal_logout_v1(p_session,p_csrf);
END $fn$;
REVOKE ALL ON FUNCTION retail.api_portal_auth_identity_v2(text),
 retail.api_portal_auth_login_v2(text,text,text,text),retail.api_portal_auth_logout_v2(text,text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION retail.api_portal_auth_identity_v2(text),
 retail.api_portal_auth_login_v2(text,text,text,text),retail.api_portal_auth_logout_v2(text,text) TO raa_wp4_portal_auth_v2;
INSERT INTO retail.schema_migrations(version,name) VALUES(27,'portal_auth_v2');
