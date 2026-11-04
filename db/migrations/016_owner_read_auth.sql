-- Read-only owner credential mapping. No decisions, sessions or dispatch.
DO $guard$
BEGIN
    IF current_database() <> 'raa_wp2_validation'
       OR NOT EXISTS (SELECT 1 FROM retail.schema_migrations WHERE version = 15)
       OR EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'raa_wp4_reviewer_api') THEN
        RAISE EXCEPTION 'Migration 015 / isolated database / new role required';
    END IF;
END
$guard$;

CREATE ROLE raa_wp4_reviewer_api NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
    NOREPLICATION NOBYPASSRLS CONNECTION LIMIT 4;
ALTER ROLE raa_wp4_reviewer_api IN DATABASE raa_wp2_validation SET statement_timeout = '5s';
ALTER ROLE raa_wp4_reviewer_api IN DATABASE raa_wp2_validation SET default_transaction_read_only = on;
GRANT CONNECT ON DATABASE raa_wp2_validation TO raa_wp4_reviewer_api;
GRANT USAGE ON SCHEMA retail TO raa_wp4_reviewer_api;

CREATE TABLE retail.owner_credentials (
    singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
    reviewer_id uuid NOT NULL UNIQUE CHECK (reviewer_id <> '00000000-0000-0000-0000-000000000000'),
    token_sha256 text NOT NULL UNIQUE CHECK (token_sha256 ~ '^[a-f0-9]{64}$'),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp() CHECK (isfinite(created_at)),
    revoked_at timestamptz CHECK (isfinite(revoked_at) AND revoked_at >= created_at)
);
REVOKE ALL ON TABLE retail.owner_credentials FROM PUBLIC;

CREATE FUNCTION retail.guard_owner_credential_v1() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, retail AS $function$
BEGIN
    IF TG_OP <> 'UPDATE' THEN RAISE EXCEPTION 'Owner credential history is retained'; END IF;
    IF NEW.singleton IS DISTINCT FROM OLD.singleton
       OR NEW.reviewer_id IS DISTINCT FROM OLD.reviewer_id
       OR NEW.token_sha256 IS DISTINCT FROM OLD.token_sha256
       OR NEW.created_at IS DISTINCT FROM OLD.created_at
       OR OLD.revoked_at IS NOT NULL OR NEW.revoked_at IS NULL THEN
        RAISE EXCEPTION 'Only one-way administrative revocation is supported';
    END IF;
    RETURN NEW;
END
$function$;
REVOKE ALL ON FUNCTION retail.guard_owner_credential_v1() FROM PUBLIC;
CREATE TRIGGER owner_credential_history BEFORE UPDATE OR DELETE ON retail.owner_credentials
    FOR EACH ROW EXECUTE FUNCTION retail.guard_owner_credential_v1();
CREATE TRIGGER owner_credential_no_truncate BEFORE TRUNCATE ON retail.owner_credentials
    FOR EACH STATEMENT EXECUTE FUNCTION retail.guard_owner_credential_v1();

CREATE FUNCTION retail.api_owner_identity_v1(p_digest text) RETURNS uuid
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, retail AS $function$
    SELECT c.reviewer_id FROM retail.owner_credentials c
    JOIN retail.approval_policies p ON p.reviewer_id = c.reviewer_id
        AND p.policy_version = 'local-publication-v1' AND p.ttl_seconds = 86400
    WHERE c.singleton AND c.revoked_at IS NULL AND c.token_sha256 = p_digest;
$function$;

CREATE FUNCTION retail.api_owner_case_v1(p_digest text, p_case_id uuid) RETURNS text
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog, retail AS $function$
BEGIN
    IF retail.api_owner_identity_v1(p_digest) IS NULL THEN
        RAISE EXCEPTION 'Unauthorized' USING ERRCODE = '42501';
    END IF;
    RETURN retail.api_get_case_v1(p_case_id);
END
$function$;

CREATE FUNCTION retail.api_owner_revision_v1(p_digest text, p_case_id uuid, p_revision integer) RETURNS text
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog, retail AS $function$
BEGIN
    IF retail.api_owner_identity_v1(p_digest) IS NULL THEN
        RAISE EXCEPTION 'Unauthorized' USING ERRCODE = '42501';
    END IF;
    IF p_revision IS DISTINCT FROM 1 THEN RETURN NULL; END IF;
    RETURN retail.api_get_revision_v1(p_case_id, p_revision);
END
$function$;

CREATE FUNCTION retail.api_owner_proposal_v1(p_digest text, p_case_id uuid) RETURNS text
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = pg_catalog, retail AS $function$
DECLARE identity uuid; result text;
BEGIN
    identity := retail.api_owner_identity_v1(p_digest);
    IF identity IS NULL THEN RAISE EXCEPTION 'Unauthorized' USING ERRCODE = '42501'; END IF;
    result := retail.api_get_approval_proposal_v1(p_case_id);
    IF result IS NOT NULL AND (result::jsonb #>> '{proposal,reviewer_id}')::uuid IS DISTINCT FROM identity THEN
        RAISE EXCEPTION 'Unauthorized' USING ERRCODE = '42501';
    END IF;
    RETURN result;
END
$function$;
REVOKE ALL ON FUNCTION retail.api_owner_identity_v1(text), retail.api_owner_case_v1(text,uuid),
    retail.api_owner_revision_v1(text,uuid,integer), retail.api_owner_proposal_v1(text,uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION retail.api_owner_identity_v1(text), retail.api_owner_case_v1(text,uuid),
    retail.api_owner_revision_v1(text,uuid,integer), retail.api_owner_proposal_v1(text,uuid)
    TO raa_wp4_reviewer_api;

INSERT INTO retail.schema_migrations(version, name) VALUES (16, 'owner_read_auth');
