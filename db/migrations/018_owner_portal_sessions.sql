-- Local validation portal. Auth-state writes only; no business decisions.
DO $guard$ BEGIN
 IF current_database()<>'raa_wp2_validation'
    OR NOT EXISTS(SELECT 1 FROM retail.schema_migrations WHERE version=17)
    OR EXISTS(SELECT 1 FROM pg_roles WHERE rolname='raa_wp4_portal_api') THEN
   RAISE EXCEPTION 'Isolated migration 017 database and new role required';
 END IF;
END $guard$;
CREATE ROLE raa_wp4_portal_api NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
 NOREPLICATION NOBYPASSRLS CONNECTION LIMIT 4;
GRANT CONNECT ON DATABASE raa_wp2_validation TO raa_wp4_portal_api;
GRANT USAGE ON SCHEMA retail TO raa_wp4_portal_api;
ALTER ROLE raa_wp4_portal_api IN DATABASE raa_wp2_validation SET statement_timeout='5s';
ALTER ROLE raa_wp4_portal_api IN DATABASE raa_wp2_validation SET default_transaction_read_only=on;

CREATE TABLE retail.owner_portal_sessions (
 session_sha256 text PRIMARY KEY CHECK(session_sha256 ~ '^[a-f0-9]{64}$'),
 reviewer_id uuid NOT NULL REFERENCES retail.owner_credentials(reviewer_id),
 csrf_sha256 text NOT NULL CHECK(csrf_sha256 ~ '^[a-f0-9]{64}$' AND csrf_sha256<>session_sha256),
 created_at timestamptz NOT NULL CHECK(isfinite(created_at)),
 expires_at timestamptz NOT NULL CHECK(isfinite(expires_at) AND expires_at=created_at+interval '1 hour'),
 revoked_at timestamptz CHECK(isfinite(revoked_at) AND revoked_at>=created_at)
);
CREATE FUNCTION retail.guard_portal_session_v1() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,retail AS $function$
BEGIN
 IF TG_OP<>'UPDATE' THEN RAISE EXCEPTION 'Session history is retained'; END IF;
 IF ROW(NEW.session_sha256,NEW.reviewer_id,NEW.csrf_sha256,NEW.created_at,NEW.expires_at)
    IS DISTINCT FROM ROW(OLD.session_sha256,OLD.reviewer_id,OLD.csrf_sha256,OLD.created_at,OLD.expires_at)
    OR OLD.revoked_at IS NOT NULL OR NEW.revoked_at IS NULL THEN
   RAISE EXCEPTION 'Only one-way session revocation is allowed';
 END IF;
 RETURN NEW;
END $function$;
CREATE TRIGGER portal_session_history BEFORE UPDATE OR DELETE ON retail.owner_portal_sessions
 FOR EACH ROW EXECUTE FUNCTION retail.guard_portal_session_v1();
CREATE TRIGGER portal_session_no_truncate BEFORE TRUNCATE ON retail.owner_portal_sessions
 FOR EACH STATEMENT EXECUTE FUNCTION retail.guard_portal_session_v1();
CREATE TABLE retail.owner_portal_events (
 event_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 session_sha256 text NOT NULL REFERENCES retail.owner_portal_sessions(session_sha256),
 event_type text NOT NULL CHECK(event_type IN ('login','logout','login_rotation')),
 occurred_at timestamptz NOT NULL CHECK(isfinite(occurred_at)),
 UNIQUE(session_sha256,event_type)
);
CREATE TRIGGER portal_event_history BEFORE UPDATE OR DELETE ON retail.owner_portal_events
 FOR EACH ROW EXECUTE FUNCTION retail.reject_source_mutation();
CREATE TRIGGER portal_event_no_truncate BEFORE TRUNCATE ON retail.owner_portal_events
 FOR EACH STATEMENT EXECUTE FUNCTION retail.reject_source_mutation();
REVOKE ALL ON TABLE retail.owner_portal_sessions,retail.owner_portal_events FROM PUBLIC;
REVOKE ALL ON FUNCTION retail.guard_portal_session_v1() FROM PUBLIC;

CREATE FUNCTION retail.api_portal_identity_v1(p_session text) RETURNS uuid
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,retail AS $function$
 SELECT s.reviewer_id FROM retail.owner_portal_sessions s
 JOIN retail.owner_credentials c ON c.reviewer_id=s.reviewer_id AND c.revoked_at IS NULL
 JOIN retail.approval_policies p ON p.reviewer_id=c.reviewer_id
   AND p.policy_version='local-publication-v1' AND p.ttl_seconds=86400
 WHERE s.session_sha256=p_session AND s.revoked_at IS NULL AND statement_timestamp()<s.expires_at;
$function$;

CREATE FUNCTION retail.api_portal_login_v1(p_owner text,p_session text,p_csrf text,p_old text) RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,retail AS $function$
DECLARE identity uuid; created timestamptz;
BEGIN
 IF p_session IS NULL OR p_session !~ '^[a-f0-9]{64}$' OR p_csrf IS NULL
    OR p_csrf !~ '^[a-f0-9]{64}$' OR p_csrf=p_session
    OR (p_old IS NOT NULL AND p_old !~ '^[a-f0-9]{64}$') THEN
   RAISE EXCEPTION 'Invalid session' USING ERRCODE='22023';
 END IF;
 -- Serializes cap, revocation check and rotation against owner revocation.
 SELECT c.reviewer_id INTO identity FROM retail.owner_credentials c
 JOIN retail.approval_policies p ON p.reviewer_id=c.reviewer_id
   AND p.policy_version='local-publication-v1' AND p.ttl_seconds=86400
 WHERE c.token_sha256=p_owner AND c.revoked_at IS NULL FOR UPDATE OF c NOWAIT;
 IF identity IS NULL THEN RAISE EXCEPTION 'Unauthorized' USING ERRCODE='42501'; END IF;
 created:=clock_timestamp();
 UPDATE retail.owner_portal_sessions SET revoked_at=created
  WHERE session_sha256=p_old AND reviewer_id=identity AND revoked_at IS NULL;
 IF FOUND THEN
   INSERT INTO retail.owner_portal_events(session_sha256,event_type,occurred_at) VALUES(p_old,'login_rotation',created);
 END IF;
 IF (SELECT count(*) FROM retail.owner_portal_sessions WHERE reviewer_id=identity
       AND revoked_at IS NULL AND expires_at>created)>=8 THEN
   RAISE EXCEPTION 'Session limit' USING ERRCODE='54000';
 END IF;
 INSERT INTO retail.owner_portal_sessions VALUES(p_session,identity,p_csrf,created,created+interval '1 hour',NULL);
 INSERT INTO retail.owner_portal_events(session_sha256,event_type,occurred_at) VALUES(p_session,'login',created);
 RETURN identity;
END $function$;

CREATE FUNCTION retail.api_portal_logout_v1(p_session text,p_csrf text) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,retail AS $function$
DECLARE identity uuid; ended timestamptz;
BEGIN
 identity:=retail.api_portal_identity_v1(p_session);
 IF identity IS NULL THEN RAISE EXCEPTION 'Unauthorized' USING ERRCODE='42501'; END IF;
 ended:=clock_timestamp();
 UPDATE retail.owner_portal_sessions SET revoked_at=ended WHERE session_sha256=p_session
   AND csrf_sha256=p_csrf AND revoked_at IS NULL AND ended<expires_at;
 IF NOT FOUND THEN RAISE EXCEPTION 'Unauthorized' USING ERRCODE='42501'; END IF;
 INSERT INTO retail.owner_portal_events(session_sha256,event_type,occurred_at) VALUES(p_session,'logout',ended);
 RETURN true;
END $function$;

CREATE FUNCTION retail.api_portal_requests_v1(p_session text) RETURNS text
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,retail SET timezone='UTC' AS $function$
DECLARE identity uuid; result text;
BEGIN
 identity:=retail.api_portal_identity_v1(p_session);
 IF identity IS NULL THEN RAISE EXCEPTION 'Unauthorized' USING ERRCODE='42501'; END IF;
 SELECT coalesce(jsonb_agg(jsonb_build_object('case_id',case_id,'proposal_id',proposal_id,
   'created_at',created_at,'expires_at',expires_at,'generation',generation,
   'review_status',CASE WHEN statement_timestamp()>=expires_at THEN 'expired' ELSE 'pending_review' END)
   ORDER BY created_at DESC),'[]'::jsonb)::text INTO result FROM (
    SELECT r.* FROM retail.approval_requests_v2 r JOIN retail.report_cases c USING(case_id)
    WHERE r.reviewer_id=identity AND c.state='awaiting_approval' AND c.current_revision=r.report_revision
      AND NOT EXISTS(SELECT 1 FROM retail.approval_requests_v2 n WHERE n.predecessor_proposal_id=r.proposal_id)
    ORDER BY r.created_at DESC LIMIT 20) latest;
 RETURN result;
END $function$;

CREATE FUNCTION retail.api_portal_request_v1(p_session text,p_case uuid,p_id uuid) RETURNS text
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,retail AS $function$
DECLARE identity uuid; result text;
BEGIN
 identity:=retail.api_portal_identity_v1(p_session);
 IF identity IS NULL THEN RAISE EXCEPTION 'Unauthorized' USING ERRCODE='42501'; END IF;
 result:=retail.api_get_approval_request_v2(p_case,p_id);
 IF result IS NOT NULL AND (result::jsonb #>> '{proposal,reviewer_id}')::uuid IS DISTINCT FROM identity THEN
   RAISE EXCEPTION 'Unauthorized' USING ERRCODE='42501';
 END IF;
 RETURN result;
END $function$;
CREATE FUNCTION retail.api_portal_case_v1(p_session text,p_case uuid) RETURNS text
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,retail AS $function$
BEGIN
 IF retail.api_portal_identity_v1(p_session) IS NULL THEN RAISE EXCEPTION 'Unauthorized' USING ERRCODE='42501'; END IF;
 RETURN retail.api_get_case_v1(p_case);
END $function$;
CREATE FUNCTION retail.api_portal_revision_v1(p_session text,p_case uuid,p_revision integer) RETURNS text
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,retail AS $function$
BEGIN
 IF retail.api_portal_identity_v1(p_session) IS NULL THEN RAISE EXCEPTION 'Unauthorized' USING ERRCODE='42501'; END IF;
 IF p_revision IS DISTINCT FROM 1 THEN RETURN NULL; END IF;
 RETURN retail.api_get_revision_v1(p_case,p_revision);
END $function$;
REVOKE ALL ON FUNCTION retail.api_portal_identity_v1(text),retail.api_portal_login_v1(text,text,text,text),
 retail.api_portal_logout_v1(text,text),retail.api_portal_requests_v1(text),
 retail.api_portal_request_v1(text,uuid,uuid),retail.api_portal_case_v1(text,uuid),
 retail.api_portal_revision_v1(text,uuid,integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION retail.api_portal_identity_v1(text),retail.api_portal_login_v1(text,text,text,text),
 retail.api_portal_logout_v1(text,text),retail.api_portal_requests_v1(text),
 retail.api_portal_request_v1(text,uuid,uuid),retail.api_portal_case_v1(text,uuid),
 retail.api_portal_revision_v1(text,uuid,integer) TO raa_wp4_portal_api;
INSERT INTO retail.schema_migrations(version,name) VALUES(18,'owner_portal_sessions');
