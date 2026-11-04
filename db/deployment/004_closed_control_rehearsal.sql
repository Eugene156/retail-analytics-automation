-- Fresh populated clone ONLY. CLOSED primitives, not a business writer fence.
DO $guard$
DECLARE suffix text:=substring(current_database() from '^raa_wp4_populated_rehearsal_([a-f0-9]{12})$');
BEGIN
 IF suffix IS NULL OR current_user IS DISTINCT FROM ('rehearsal_admin_'||suffix)
  OR session_user IS DISTINCT FROM current_user OR pg_is_in_recovery()
  OR (SELECT system_identifier::text FROM pg_control_system()) IS DISTINCT FROM current_setting('raa.rehearsal_system',true)
  OR coalesce(current_setting('raa.rehearsal_system',true),'') !~ '^[0-9]{10,20}$'
  OR coalesce(current_setting('raa.checkpoint_id',true),'') !~ '^[a-f0-9]{8}(-[a-f0-9]{4}){3}-[a-f0-9]{12}$'
  OR coalesce(current_setting('raa.deployment_id',true),'') !~ '^[a-f0-9]{8}(-[a-f0-9]{4}){3}-[a-f0-9]{12}$'
  OR coalesce(current_setting('raa.predecessor_id',true),'') !~ '^[a-f0-9]{8}(-[a-f0-9]{4}){3}-[a-f0-9]{12}$'
  OR coalesce(current_setting('raa.source_digest',true),'') !~ '^[a-f0-9]{64}$'
  OR coalesce(current_setting('raa.bundle_digest',true),'') !~ '^[a-f0-9]{64}$'
  OR coalesce(current_setting('raa.predecessor_digest',true),'') !~ '^[a-f0-9]{64}$'
  OR coalesce(current_setting('raa.baseline_digest',true),'') !~ '^[a-f0-9]{64}$' THEN
  RAISE EXCEPTION 'Exact fresh clone context required'; END IF;
 IF NOT pg_try_advisory_xact_lock(hashtextextended('wp4-populated-deployment001',0)) THEN
  RAISE EXCEPTION 'Deployment is busy' USING ERRCODE='55P03'; END IF;
 IF to_regclass('raa_deployment.acl_hardening_releases') IS NULL THEN
  RAISE EXCEPTION 'Committed deployment003 required'; END IF;
 IF NOT EXISTS(SELECT FROM raa_deployment.acl_hardening_releases r
   WHERE r.bundle_id='wp4-rehearsal-003' AND r.deployment_id=current_setting('raa.predecessor_id')::uuid
   AND r.bundle_digest=current_setting('raa.predecessor_digest')
   AND r.checkpoint_id=current_setting('raa.checkpoint_id')::uuid
   AND r.source_digest=current_setting('raa.source_digest') AND r.baseline_digest=current_setting('raa.baseline_digest')
   AND r.target_system=current_setting('raa.rehearsal_system') AND r.target_database=current_database()
   AND r.base_version=20 AND NOT r.admitted)
  OR (SELECT count(*) FROM raa_deployment.acl_hardening_releases)<>1
  OR to_regnamespace('raa_closed_control') IS NOT NULL
  OR EXISTS(SELECT FROM pg_roles WHERE rolname='raa_wp4_closed_controller_v1')
  OR (SELECT array_agg(version ORDER BY version) FROM retail.schema_migrations) IS DISTINCT FROM ARRAY(SELECT generate_series(1,20))
  OR EXISTS(SELECT FROM pg_prepared_xacts)
  OR EXISTS(SELECT FROM retail.portal_approval_requests_v3) OR EXISTS(SELECT FROM retail.portal_worker_events_v1)
  OR EXISTS(SELECT FROM retail.portal_review_decisions_v2) OR EXISTS(SELECT FROM retail.portal_publications_v2)
  OR EXISTS(SELECT FROM retail.portal_publication_intents_v2)
  OR EXISTS(SELECT FROM pg_roles WHERE (rolname='g0_user' OR rolname LIKE 'raa\_%' ESCAPE '\')
     AND (rolcanlogin OR rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication OR rolbypassrls)) THEN
  RAISE EXCEPTION 'Exact non-admitted003 predecessor required'; END IF;
END $guard$;

CREATE ROLE raa_wp4_closed_controller_v1 NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
CREATE SCHEMA raa_closed_control;
REVOKE ALL ON SCHEMA raa_closed_control FROM PUBLIC;
GRANT USAGE ON SCHEMA raa_closed_control TO raa_wp4_closed_controller_v1;

CREATE TABLE raa_closed_control.releases (
 bundle_id text PRIMARY KEY CHECK(bundle_id='wp4-rehearsal-004-closed'),
 deployment_id uuid NOT NULL UNIQUE, checkpoint_id uuid NOT NULL,
 predecessor_id uuid NOT NULL REFERENCES raa_deployment.acl_hardening_releases(deployment_id),
 predecessor_digest text NOT NULL CHECK(predecessor_digest ~ '^[a-f0-9]{64}$'),
 source_digest text NOT NULL CHECK(source_digest ~ '^[a-f0-9]{64}$'),
 bundle_digest text NOT NULL CHECK(bundle_digest ~ '^[a-f0-9]{64}$'),
 baseline_digest text NOT NULL CHECK(baseline_digest ~ '^[a-f0-9]{64}$'),
 base_version integer NOT NULL CHECK(base_version=20),
 target_database name NOT NULL CHECK(target_database::text ~ '^raa_wp4_populated_rehearsal_[a-f0-9]{12}$'),
 target_system text NOT NULL CHECK(target_system ~ '^[0-9]{10,20}$'),
 installed_at timestamptz NOT NULL CHECK(isfinite(installed_at)),
 admitted boolean NOT NULL DEFAULT false CHECK(admitted=false)
);
CREATE TABLE raa_closed_control.events (
 operation_id uuid PRIMARY KEY, controller_id uuid NOT NULL,
 previous_generation bigint NOT NULL CHECK(previous_generation>=0),
 generation bigint NOT NULL UNIQUE CHECK(generation=previous_generation+1),
 candidate_epoch uuid NOT NULL UNIQUE,
 candidate_digest text NOT NULL CHECK(candidate_digest ~ '^[a-f0-9]{64}$'),
 state text NOT NULL CHECK(state='CLOSED'),
 recorded_at timestamptz NOT NULL CHECK(isfinite(recorded_at)),
 deployment_id uuid NOT NULL REFERENCES raa_closed_control.releases(deployment_id)
);
CREATE TABLE raa_closed_control.latch (
 singleton boolean PRIMARY KEY CHECK(singleton=true),
 state text NOT NULL CHECK(state='CLOSED'), generation bigint NOT NULL CHECK(generation>=0),
 controller_id uuid, operation_id uuid REFERENCES raa_closed_control.events(operation_id), candidate_epoch uuid,
 CHECK((generation=0 AND controller_id IS NULL AND operation_id IS NULL AND candidate_epoch IS NULL)
   OR (generation>0 AND controller_id IS NOT NULL AND operation_id IS NOT NULL AND candidate_epoch IS NOT NULL))
);
REVOKE ALL ON ALL TABLES IN SCHEMA raa_closed_control FROM PUBLIC;

CREATE FUNCTION raa_closed_control.reject_mutation_v1() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,raa_closed_control AS $body$
BEGIN RAISE EXCEPTION 'Immutable closed-control evidence' USING ERRCODE='55000'; END $body$;
CREATE TRIGGER immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON raa_closed_control.releases
 FOR EACH STATEMENT EXECUTE FUNCTION raa_closed_control.reject_mutation_v1();
CREATE TRIGGER immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON raa_closed_control.events
 FOR EACH STATEMENT EXECUTE FUNCTION raa_closed_control.reject_mutation_v1();
CREATE TRIGGER no_removal BEFORE DELETE OR TRUNCATE ON raa_closed_control.latch
 FOR EACH STATEMENT EXECUTE FUNCTION raa_closed_control.reject_mutation_v1();

CREATE FUNCTION raa_closed_control.guard_latch_v1() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,raa_closed_control AS $body$
BEGIN
 IF NEW.state<>'CLOSED' OR NEW.singleton IS DISTINCT FROM OLD.singleton
  OR NEW.generation<>OLD.generation+1
  OR (OLD.controller_id IS NOT NULL AND NEW.controller_id IS DISTINCT FROM OLD.controller_id)
  OR NOT EXISTS(SELECT FROM raa_closed_control.events e WHERE e.operation_id=NEW.operation_id
   AND e.controller_id=NEW.controller_id AND e.generation=NEW.generation
   AND e.previous_generation=OLD.generation AND e.candidate_epoch=NEW.candidate_epoch AND e.state='CLOSED') THEN
  RAISE EXCEPTION 'Exact closed event and generation required' USING ERRCODE='55000'; END IF;
 RETURN NEW;
END $body$;
CREATE TRIGGER exact_update BEFORE UPDATE ON raa_closed_control.latch
 FOR EACH ROW EXECUTE FUNCTION raa_closed_control.guard_latch_v1();

CREATE FUNCTION raa_closed_control.check_target_v1() RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,raa_closed_control AS $body$
BEGIN
 IF current_database() !~ '^raa_wp4_populated_rehearsal_[a-f0-9]{12}$'
  OR session_user IS DISTINCT FROM ('rehearsal_admin_'||right(current_database(),12))
  OR pg_is_in_recovery() OR (SELECT count(*) FROM raa_closed_control.releases)<>1
  OR NOT EXISTS(SELECT FROM raa_closed_control.releases r WHERE r.target_database=current_database()
    AND r.target_system=(SELECT system_identifier::text FROM pg_control_system()) AND NOT r.admitted) THEN
  RAISE EXCEPTION 'Exact non-admitted clone required' USING ERRCODE='55000'; END IF;
END $body$;

CREATE FUNCTION raa_closed_control.api_closed_state_v1() RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,raa_closed_control AS $body$
DECLARE result jsonb;
BEGIN
 PERFORM raa_closed_control.check_target_v1();
 SELECT to_jsonb(l)||jsonb_build_object('events',(SELECT count(*) FROM raa_closed_control.events),
  'application_writers_admitted',false) INTO STRICT result FROM raa_closed_control.latch l;
 RETURN result;
END $body$;

CREATE FUNCTION raa_closed_control.api_close_v1(p_controller uuid,p_expected bigint,p_operation uuid,p_epoch uuid,p_digest text)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,raa_closed_control AS $body$
DECLARE old raa_closed_control.latch; saved raa_closed_control.events;
BEGIN
 PERFORM raa_closed_control.check_target_v1();
 IF p_controller IS NULL OR p_expected IS NULL OR p_expected<0 OR p_operation IS NULL OR p_epoch IS NULL
  OR p_digest IS NULL OR p_digest !~ '^[a-f0-9]{64}$' THEN
  RAISE EXCEPTION 'Exact closed operation binding required' USING ERRCODE='22023'; END IF;
 SELECT * INTO STRICT old FROM raa_closed_control.latch WHERE singleton FOR UPDATE;
 SELECT * INTO saved FROM raa_closed_control.events WHERE operation_id=p_operation;
 IF FOUND THEN
  IF saved.controller_id<>p_controller OR saved.previous_generation<>p_expected
   OR saved.candidate_epoch<>p_epoch OR saved.candidate_digest<>p_digest THEN
   RAISE EXCEPTION 'Conflicting closed operation' USING ERRCODE='22023'; END IF;
  RETURN to_jsonb(saved)||jsonb_build_object('application_writers_admitted',false);
 END IF;
 IF old.generation<>p_expected OR (old.controller_id IS NOT NULL AND old.controller_id<>p_controller) THEN
  RAISE EXCEPTION 'Stale or competing controller' USING ERRCODE='55000'; END IF;
 IF EXISTS(SELECT FROM raa_closed_control.events WHERE candidate_epoch=p_epoch) THEN
  RAISE EXCEPTION 'Candidate epoch cannot be reused' USING ERRCODE='22023'; END IF;
 INSERT INTO raa_closed_control.events
  SELECT p_operation,p_controller,p_expected,p_expected+1,p_epoch,p_digest,'CLOSED',clock_timestamp(),deployment_id
  FROM raa_closed_control.releases RETURNING * INTO STRICT saved;
 UPDATE raa_closed_control.latch SET state='CLOSED',generation=saved.generation,
  controller_id=p_controller,operation_id=p_operation,candidate_epoch=p_epoch WHERE singleton;
 RETURN to_jsonb(saved)||jsonb_build_object('application_writers_admitted',false);
END $body$;

CREATE FUNCTION raa_closed_control.api_reconcile_close_v1(p_controller uuid,p_expected bigint,p_operation uuid,p_epoch uuid,p_digest text)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,raa_closed_control AS $body$
DECLARE saved raa_closed_control.events;
BEGIN
 PERFORM raa_closed_control.check_target_v1();
 IF p_controller IS NULL OR p_expected IS NULL OR p_expected<0 OR p_operation IS NULL OR p_epoch IS NULL
  OR p_digest IS NULL OR p_digest !~ '^[a-f0-9]{64}$' THEN
  RAISE EXCEPTION 'Exact reconciliation binding required' USING ERRCODE='22023'; END IF;
 SELECT * INTO saved FROM raa_closed_control.events WHERE operation_id=p_operation;
 IF NOT FOUND THEN RETURN NULL; END IF;
 IF saved.controller_id<>p_controller OR saved.previous_generation<>p_expected
  OR saved.candidate_epoch<>p_epoch OR saved.candidate_digest<>p_digest THEN
  RAISE EXCEPTION 'Conflicting reconciliation' USING ERRCODE='22023'; END IF;
 RETURN to_jsonb(saved)||jsonb_build_object('application_writers_admitted',false);
END $body$;

CREATE FUNCTION raa_closed_control.api_deny_runtime_v1() RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,raa_closed_control AS $body$
BEGIN
 PERFORM raa_closed_control.check_target_v1();
 PERFORM 1 FROM raa_closed_control.latch WHERE singleton FOR SHARE;
 RAISE EXCEPTION 'Runtime admission is not implemented' USING ERRCODE='55000';
END $body$;

REVOKE ALL ON ALL FUNCTIONS IN SCHEMA raa_closed_control FROM PUBLIC;
GRANT EXECUTE ON FUNCTION raa_closed_control.api_closed_state_v1(),
 raa_closed_control.api_close_v1(uuid,bigint,uuid,uuid,text),
 raa_closed_control.api_reconcile_close_v1(uuid,bigint,uuid,uuid,text),
 raa_closed_control.api_deny_runtime_v1() TO raa_wp4_closed_controller_v1;

INSERT INTO raa_closed_control.releases
 SELECT 'wp4-rehearsal-004-closed',current_setting('raa.deployment_id')::uuid,current_setting('raa.checkpoint_id')::uuid,
 current_setting('raa.predecessor_id')::uuid,current_setting('raa.predecessor_digest'),current_setting('raa.source_digest'),
 current_setting('raa.bundle_digest'),current_setting('raa.baseline_digest'),20,current_database(),
 (SELECT system_identifier::text FROM pg_control_system()),clock_timestamp(),false;
INSERT INTO raa_closed_control.latch VALUES(true,'CLOSED',0,NULL,NULL,NULL);
