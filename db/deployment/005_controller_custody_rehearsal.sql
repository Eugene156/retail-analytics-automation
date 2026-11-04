-- Fresh populated clone ONLY. Physical-connection custody; never admission.
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
 IF to_regclass('raa_closed_control.releases') IS NULL THEN
  RAISE EXCEPTION 'Committed deployment004 required'; END IF;
 IF NOT EXISTS(SELECT FROM raa_closed_control.releases r
   WHERE r.bundle_id='wp4-rehearsal-004-closed' AND r.deployment_id=current_setting('raa.predecessor_id')::uuid
   AND r.bundle_digest=current_setting('raa.predecessor_digest')
   AND r.checkpoint_id=current_setting('raa.checkpoint_id')::uuid
   AND r.source_digest=current_setting('raa.source_digest') AND r.baseline_digest=current_setting('raa.baseline_digest')
   AND r.target_system=current_setting('raa.rehearsal_system') AND r.target_database=current_database()
   AND r.base_version=20 AND NOT r.admitted)
  OR (SELECT count(*) FROM raa_closed_control.releases)<>1
  OR to_regclass('raa_closed_control.custody_releases') IS NOT NULL
  OR NOT EXISTS(SELECT FROM raa_closed_control.latch WHERE singleton AND state='CLOSED'
      AND controller_id IS NOT NULL AND generation=(SELECT count(*) FROM raa_closed_control.events))
  OR (SELECT array_agg(version ORDER BY version) FROM retail.schema_migrations) IS DISTINCT FROM ARRAY(SELECT generate_series(1,20))
  OR EXISTS(SELECT FROM pg_prepared_xacts)
  OR EXISTS(SELECT FROM pg_stat_activity WHERE pid<>pg_backend_pid() AND backend_type NOT IN
      ('autovacuum launcher','autovacuum worker','background writer','checkpointer','walwriter','archiver','logical replication launcher'))
  OR EXISTS(SELECT FROM pg_roles WHERE (rolname='g0_user' OR rolname LIKE 'raa\_%' ESCAPE '\')
     AND (rolcanlogin OR rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication OR rolbypassrls)) THEN
  RAISE EXCEPTION 'Exact quiescent CLOSED004 predecessor required'; END IF;
END $guard$;

CREATE TABLE raa_closed_control.custody_releases (
 bundle_id text PRIMARY KEY CHECK(bundle_id='wp4-rehearsal-005-custody'),
 deployment_id uuid NOT NULL UNIQUE, checkpoint_id uuid NOT NULL,
 predecessor_id uuid NOT NULL REFERENCES raa_closed_control.releases(deployment_id),
 predecessor_digest text NOT NULL CHECK(predecessor_digest ~ '^[a-f0-9]{64}$'),
 source_digest text NOT NULL CHECK(source_digest ~ '^[a-f0-9]{64}$'),
 bundle_digest text NOT NULL CHECK(bundle_digest ~ '^[a-f0-9]{64}$'),
 baseline_digest text NOT NULL CHECK(baseline_digest ~ '^[a-f0-9]{64}$'),
 base_version integer NOT NULL CHECK(base_version=20),
 target_database name NOT NULL, target_system text NOT NULL,
 postmaster_start timestamptz NOT NULL CHECK(isfinite(postmaster_start)),
 installed_at timestamptz NOT NULL CHECK(isfinite(installed_at)),
 admitted boolean NOT NULL DEFAULT false CHECK(admitted=false)
);
CREATE TABLE raa_closed_control.custody (
 singleton boolean PRIMARY KEY CHECK(singleton=true),
 claim_key uuid NOT NULL UNIQUE,
 custody_release_id uuid NOT NULL UNIQUE DEFAULT gen_random_uuid(),
 controller_id uuid NOT NULL,
 original_generation bigint NOT NULL CHECK(original_generation>=0),
 identity jsonb NOT NULL CHECK(jsonb_typeof(identity)='object'),
 deployment_id uuid NOT NULL REFERENCES raa_closed_control.custody_releases(deployment_id),
 claimed_at timestamptz NOT NULL CHECK(isfinite(claimed_at))
);
REVOKE ALL ON raa_closed_control.custody_releases,raa_closed_control.custody FROM PUBLIC;
CREATE TRIGGER immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON raa_closed_control.custody_releases
 FOR EACH STATEMENT EXECUTE FUNCTION raa_closed_control.reject_mutation_v1();
CREATE TRIGGER immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON raa_closed_control.custody
 FOR EACH STATEMENT EXECUTE FUNCTION raa_closed_control.reject_mutation_v1();

CREATE FUNCTION raa_closed_control.self_identity_v1() RETURNS jsonb
LANGUAGE sql VOLATILE PARALLEL UNSAFE SECURITY DEFINER SET search_path=pg_catalog,raa_closed_control AS $body$
 SELECT jsonb_build_object('system_identifier',(SELECT system_identifier::text FROM pg_control_system()),
  'postmaster_start',pg_postmaster_start_time(),'database_oid',a.datid::bigint,
  'session_user_oid',(SELECT oid::bigint FROM pg_roles WHERE rolname=session_user),
  'backend_pid',a.pid,'backend_start',a.backend_start)
 FROM pg_stat_activity a WHERE a.pid=pg_backend_pid()
$body$;

CREATE FUNCTION raa_closed_control.check_custody_target_v1() RETURNS void
LANGUAGE plpgsql VOLATILE PARALLEL UNSAFE SECURITY DEFINER SET search_path=pg_catalog,raa_closed_control AS $body$
BEGIN
 PERFORM raa_closed_control.check_target_v1();
 IF (SELECT count(*) FROM raa_closed_control.custody_releases)<>1 OR NOT EXISTS(
  SELECT FROM raa_closed_control.custody_releases r WHERE r.target_database=current_database()
   AND r.target_system=(SELECT system_identifier::text FROM pg_control_system())
   AND r.postmaster_start=pg_postmaster_start_time() AND NOT r.admitted) THEN
  RAISE EXCEPTION 'Original custody server epoch required' USING ERRCODE='55000'; END IF;
END $body$;

CREATE FUNCTION raa_closed_control.api_claim_custody_v1(p_claim_key uuid) RETURNS jsonb
LANGUAGE plpgsql VOLATILE PARALLEL UNSAFE CALLED ON NULL INPUT SECURITY DEFINER SET search_path=pg_catalog,raa_closed_control AS $body$
DECLARE l raa_closed_control.latch%ROWTYPE; original raa_closed_control.custody%ROWTYPE; own jsonb;
BEGIN
 PERFORM raa_closed_control.check_custody_target_v1();
 IF p_claim_key IS NULL THEN RAISE EXCEPTION 'Claim key required' USING ERRCODE='22023'; END IF;
 SELECT * INTO STRICT l FROM raa_closed_control.latch WHERE singleton FOR UPDATE;
 own:=raa_closed_control.self_identity_v1();
 IF own IS NULL OR l.state<>'CLOSED' THEN RAISE EXCEPTION 'CLOSED owner required' USING ERRCODE='55000'; END IF;
 IF EXISTS(SELECT FROM pg_prepared_xacts) OR EXISTS(SELECT FROM pg_stat_activity
  WHERE pid<>pg_backend_pid() AND backend_type NOT IN
   ('autovacuum launcher','autovacuum worker','background writer','checkpointer','walwriter','archiver','logical replication launcher')) THEN
  RAISE EXCEPTION 'Other connection or prepared transaction blocks claim' USING ERRCODE='55000'; END IF;
 SELECT * INTO original FROM raa_closed_control.custody WHERE singleton;
 IF FOUND THEN
  IF original.identity IS DISTINCT FROM own THEN
   RAISE EXCEPTION 'Original physical connection required; no takeover' USING ERRCODE='55000'; END IF;
  IF original.claim_key IS DISTINCT FROM p_claim_key THEN
   RAISE EXCEPTION 'Original claim binding required' USING ERRCODE='22023'; END IF;
  RETURN to_jsonb(original);
 END IF;
 INSERT INTO raa_closed_control.custody(singleton,claim_key,controller_id,original_generation,identity,deployment_id,claimed_at)
 VALUES(true,p_claim_key,l.controller_id,l.generation,own,(SELECT deployment_id FROM raa_closed_control.custody_releases),clock_timestamp())
 RETURNING * INTO original;
 RETURN to_jsonb(original);
END $body$;

CREATE FUNCTION raa_closed_control.api_owned_close_v1(p_claim_key uuid,p_generation bigint,p_operation uuid,p_epoch uuid,p_digest text) RETURNS jsonb
LANGUAGE plpgsql VOLATILE PARALLEL UNSAFE CALLED ON NULL INPUT SECURITY DEFINER SET search_path=pg_catalog,raa_closed_control AS $body$
DECLARE original raa_closed_control.custody%ROWTYPE;
BEGIN
 PERFORM raa_closed_control.check_custody_target_v1();
 PERFORM 1 FROM raa_closed_control.latch WHERE singleton FOR UPDATE;
 SELECT * INTO original FROM raa_closed_control.custody WHERE singleton;
 IF NOT FOUND OR original.identity IS DISTINCT FROM raa_closed_control.self_identity_v1()
  OR original.claim_key IS DISTINCT FROM p_claim_key THEN
  RAISE EXCEPTION 'Original physical connection and claim required' USING ERRCODE='55000'; END IF;
 RETURN raa_closed_control.api_close_v1(original.controller_id,p_generation,p_operation,p_epoch,p_digest);
END $body$;

REVOKE ALL ON FUNCTION raa_closed_control.self_identity_v1(),raa_closed_control.check_custody_target_v1(),
 raa_closed_control.api_claim_custody_v1(uuid),raa_closed_control.api_owned_close_v1(uuid,bigint,uuid,uuid,text) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION raa_closed_control.api_close_v1(uuid,bigint,uuid,uuid,text) FROM raa_wp4_closed_controller_v1;
GRANT EXECUTE ON FUNCTION raa_closed_control.api_claim_custody_v1(uuid),
 raa_closed_control.api_owned_close_v1(uuid,bigint,uuid,uuid,text) TO raa_wp4_closed_controller_v1;

INSERT INTO raa_closed_control.custody_releases VALUES('wp4-rehearsal-005-custody',
 current_setting('raa.deployment_id')::uuid,current_setting('raa.checkpoint_id')::uuid,
 current_setting('raa.predecessor_id')::uuid,current_setting('raa.predecessor_digest'),
 current_setting('raa.source_digest'),current_setting('raa.bundle_digest'),current_setting('raa.baseline_digest'),
 20,current_database(),current_setting('raa.rehearsal_system'),pg_postmaster_start_time(),clock_timestamp(),false);
