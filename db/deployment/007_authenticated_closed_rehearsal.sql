-- OFFLINE FOUNDATION. Not wired into any installer/runtime; native proof pending.
-- Additive fresh clone007 only. Existing001-006 definitions/custody never changed.
DO $guard$
DECLARE suffix text:=substring(current_database() from '^raa_wp4_populated_rehearsal_([a-f0-9]{12})$');
BEGIN
 IF suffix IS NULL OR current_user IS DISTINCT FROM ('rehearsal_admin_'||suffix)
  OR session_user IS DISTINCT FROM current_user OR pg_is_in_recovery()
  OR coalesce(current_setting('raa.rehearsal_system',true),'') !~ '^[0-9]{10,20}$'
  OR current_setting('raa.rehearsal_system',true) IS DISTINCT FROM (SELECT system_identifier::text FROM pg_control_system())
  OR coalesce(current_setting('raa.checkpoint_id',true),'') !~ '^[a-f0-9]{8}(-[a-f0-9]{4}){3}-[a-f0-9]{12}$'
  OR coalesce(current_setting('raa.deployment_id',true),'') !~ '^[a-f0-9]{8}(-[a-f0-9]{4}){3}-[a-f0-9]{12}$'
  OR coalesce(current_setting('raa.predecessor_id',true),'') !~ '^[a-f0-9]{8}(-[a-f0-9]{4}){3}-[a-f0-9]{12}$'
  OR coalesce(current_setting('raa.source_digest',true),'') !~ '^[a-f0-9]{64}$'
  OR coalesce(current_setting('raa.bundle_digest',true),'') !~ '^[a-f0-9]{64}$'
  OR coalesce(current_setting('raa.predecessor_digest',true),'') !~ '^[a-f0-9]{64}$'
  OR coalesce(current_setting('raa.baseline_digest',true),'') !~ '^[a-f0-9]{64}$' THEN
  RAISE EXCEPTION 'Exact fresh clone context required' USING ERRCODE='55000'; END IF;
 IF NOT pg_try_advisory_xact_lock(hashtextextended('wp4-populated-deployment001',0)) THEN
  RAISE EXCEPTION 'Deployment busy' USING ERRCODE='55P03'; END IF;
 IF to_regclass('raa_closed_control.business_guard_releases') IS NULL
  OR to_regnamespace('raa_authenticated_closed') IS NOT NULL THEN
  RAISE EXCEPTION 'Fresh committed006 predecessor required' USING ERRCODE='55000'; END IF;
 IF (SELECT count(*) FROM raa_closed_control.business_guard_releases)<>1
  OR NOT EXISTS(SELECT FROM raa_closed_control.business_guard_releases r
   WHERE r.bundle_id='wp4-rehearsal-006-business-closed'
    AND r.deployment_id=current_setting('raa.predecessor_id')::uuid
    AND r.bundle_digest=current_setting('raa.predecessor_digest')
    AND r.checkpoint_id=current_setting('raa.checkpoint_id')::uuid
    AND r.source_digest=current_setting('raa.source_digest') AND r.baseline_digest=current_setting('raa.baseline_digest')
    AND r.target_database=current_database() AND r.target_system=current_setting('raa.rehearsal_system')
    AND r.postmaster_start=pg_postmaster_start_time() AND r.base_version=20 AND NOT r.admitted)
  OR (SELECT count(*) FROM raa_closed_control.custody)<>1
  OR (SELECT count(*) FROM raa_closed_control.custody_releases)<>1
  OR NOT EXISTS(SELECT FROM raa_closed_control.latch WHERE singleton AND state='CLOSED'
    AND generation=(SELECT count(*) FROM raa_closed_control.events))
  OR (SELECT array_agg(version ORDER BY version) FROM retail.schema_migrations) IS DISTINCT FROM ARRAY(SELECT generate_series(1,20))
  OR EXISTS(SELECT FROM pg_prepared_xacts)
  OR EXISTS(SELECT FROM pg_stat_activity WHERE pid<>pg_backend_pid() AND backend_type NOT IN
    ('autovacuum launcher','autovacuum worker','background writer','checkpointer','walwriter','archiver','logical replication launcher'))
  OR EXISTS(SELECT FROM pg_roles WHERE (rolname='g0_user' OR starts_with(rolname,'raa_'))
    AND (rolcanlogin OR rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication OR rolbypassrls))
  OR EXISTS(SELECT FROM pg_auth_members m JOIN pg_roles a ON a.oid=m.roleid JOIN pg_roles b ON b.oid=m.member
    WHERE a.rolname='g0_user' OR b.rolname='g0_user' OR starts_with(a.rolname,'raa_') OR starts_with(b.rolname,'raa_')) THEN
  RAISE EXCEPTION 'Exact quiescent CLOSED006 predecessor required' USING ERRCODE='55000'; END IF;
END $guard$;

CREATE SCHEMA raa_authenticated_closed;
REVOKE ALL ON SCHEMA raa_authenticated_closed FROM PUBLIC;
CREATE TABLE raa_authenticated_closed.releases (
 bundle_id text PRIMARY KEY CHECK(bundle_id='wp4-rehearsal-007-authenticated-closed'),
 deployment_id uuid NOT NULL UNIQUE, checkpoint_id uuid NOT NULL,
 predecessor_id uuid NOT NULL REFERENCES raa_closed_control.business_guard_releases(deployment_id),
 predecessor_digest text NOT NULL CHECK(predecessor_digest ~ '^[a-f0-9]{64}$'),
 source_digest text NOT NULL CHECK(source_digest ~ '^[a-f0-9]{64}$'),
 bundle_digest text NOT NULL CHECK(bundle_digest ~ '^[a-f0-9]{64}$'),
 baseline_digest text NOT NULL CHECK(baseline_digest ~ '^[a-f0-9]{64}$'),
 target_database name NOT NULL, database_oid oid NOT NULL, target_system text NOT NULL,
 postmaster_start timestamptz NOT NULL CHECK(isfinite(postmaster_start)),
 custody_release_id uuid NOT NULL UNIQUE DEFAULT gen_random_uuid(),
 installed_at timestamptz NOT NULL DEFAULT clock_timestamp() CHECK(isfinite(installed_at)),
 admitted boolean NOT NULL DEFAULT false CHECK(admitted=false)
);
CREATE TABLE raa_authenticated_closed.principals (
 role_oid oid PRIMARY KEY, role_name name NOT NULL UNIQUE,
 kind text NOT NULL CHECK(kind IN ('controller','observer','probe')),
 source_scope name UNIQUE, allowed_functions oid[] NOT NULL,
 CHECK((kind='probe')=(source_scope IS NOT NULL)),
 CHECK(cardinality(allowed_functions)>0)
);
CREATE UNIQUE INDEX one_controller ON raa_authenticated_closed.principals(kind) WHERE kind='controller';
CREATE UNIQUE INDEX one_observer ON raa_authenticated_closed.principals(kind) WHERE kind='observer';
CREATE TABLE raa_authenticated_closed.custody (
 singleton boolean PRIMARY KEY CHECK(singleton=true), claim_key uuid NOT NULL UNIQUE,
 identity jsonb NOT NULL CHECK(jsonb_typeof(identity)='object'),
 deployment_id uuid NOT NULL REFERENCES raa_authenticated_closed.releases(deployment_id),
 claimed_at timestamptz NOT NULL DEFAULT clock_timestamp() CHECK(isfinite(claimed_at))
);
CREATE TABLE raa_authenticated_closed.events (
 operation_id uuid PRIMARY KEY, claim_key uuid NOT NULL REFERENCES raa_authenticated_closed.custody(claim_key),
 previous_generation bigint NOT NULL CHECK(previous_generation>=0),
 generation bigint NOT NULL UNIQUE CHECK(generation=previous_generation+1),
 candidate_epoch uuid NOT NULL UNIQUE, candidate_digest text NOT NULL CHECK(candidate_digest ~ '^[a-f0-9]{64}$'),
 state text NOT NULL CHECK(state='CLOSED'),
 recorded_at timestamptz NOT NULL DEFAULT clock_timestamp() CHECK(isfinite(recorded_at))
);
CREATE TABLE raa_authenticated_closed.latch (
 singleton boolean PRIMARY KEY CHECK(singleton=true), state text NOT NULL CHECK(state='CLOSED'),
 generation bigint NOT NULL CHECK(generation>=0), operation_id uuid REFERENCES raa_authenticated_closed.events(operation_id),
 CHECK((generation=0)=(operation_id IS NULL))
);
REVOKE ALL ON ALL TABLES IN SCHEMA raa_authenticated_closed FROM PUBLIC;

CREATE FUNCTION raa_authenticated_closed.reject_mutation_v1() RETURNS trigger
LANGUAGE plpgsql VOLATILE PARALLEL UNSAFE CALLED ON NULL INPUT SECURITY DEFINER SET search_path=pg_catalog,raa_authenticated_closed AS $body$
BEGIN RAISE EXCEPTION 'Immutable authenticated CLOSED evidence' USING ERRCODE='55000'; END $body$;
CREATE TRIGGER immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON raa_authenticated_closed.releases
 FOR EACH STATEMENT EXECUTE FUNCTION raa_authenticated_closed.reject_mutation_v1();
CREATE TRIGGER immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON raa_authenticated_closed.principals
 FOR EACH STATEMENT EXECUTE FUNCTION raa_authenticated_closed.reject_mutation_v1();
CREATE TRIGGER immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON raa_authenticated_closed.custody
 FOR EACH STATEMENT EXECUTE FUNCTION raa_authenticated_closed.reject_mutation_v1();
CREATE TRIGGER immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON raa_authenticated_closed.events
 FOR EACH STATEMENT EXECUTE FUNCTION raa_authenticated_closed.reject_mutation_v1();
CREATE TRIGGER no_removal BEFORE DELETE OR TRUNCATE ON raa_authenticated_closed.latch
 FOR EACH STATEMENT EXECUTE FUNCTION raa_authenticated_closed.reject_mutation_v1();

CREATE FUNCTION raa_authenticated_closed.guard_latch_v1() RETURNS trigger
LANGUAGE plpgsql VOLATILE PARALLEL UNSAFE CALLED ON NULL INPUT SECURITY DEFINER SET search_path=pg_catalog,raa_authenticated_closed AS $body$
BEGIN
 IF NEW.singleton IS DISTINCT FROM OLD.singleton OR NEW.state<>'CLOSED' OR NEW.generation<>OLD.generation+1
  OR NOT EXISTS(SELECT FROM raa_authenticated_closed.events e WHERE e.operation_id=NEW.operation_id
    AND e.generation=NEW.generation AND e.previous_generation=OLD.generation AND e.state='CLOSED') THEN
  RAISE EXCEPTION 'Exact CLOSED event required' USING ERRCODE='55000'; END IF;
 RETURN NEW;
END $body$;
CREATE TRIGGER exact_update BEFORE UPDATE ON raa_authenticated_closed.latch
 FOR EACH ROW EXECUTE FUNCTION raa_authenticated_closed.guard_latch_v1();

CREATE FUNCTION raa_authenticated_closed.self_identity_v1() RETURNS jsonb
LANGUAGE sql VOLATILE PARALLEL UNSAFE CALLED ON NULL INPUT SECURITY DEFINER SET search_path=pg_catalog,raa_authenticated_closed AS $body$
 SELECT jsonb_build_object('system_identifier',(SELECT system_identifier::text FROM pg_control_system()),
  'postmaster_start',pg_postmaster_start_time(),'database_oid',a.datid::bigint,
  'session_user_oid',(SELECT oid::bigint FROM pg_roles WHERE rolname=session_user),
  'backend_pid',a.pid,'backend_start',a.backend_start,
  'custody_release_id',(SELECT custody_release_id FROM raa_authenticated_closed.releases))
 FROM pg_stat_activity a WHERE a.pid=pg_backend_pid()
$body$;

-- Check server-derived authenticated identity and the whole exact registered ACL
-- projection every entry. No GUC, application label, SET ROLE or cached permit.
CREATE FUNCTION raa_authenticated_closed.check_target_v1(p_mutation boolean) RETURNS boolean
LANGUAGE plpgsql VOLATILE PARALLEL UNSAFE CALLED ON NULL INPUT SECURITY DEFINER SET search_path=pg_catalog,raa_authenticated_closed AS $body$
DECLARE release raa_authenticated_closed.releases; principal raa_authenticated_closed.principals; role_record record; epoch_current boolean;
BEGIN
 IF p_mutation IS NULL OR current_database() !~ '^raa_wp4_populated_rehearsal_[a-f0-9]{12}$' OR pg_is_in_recovery()
  OR (SELECT count(*) FROM raa_authenticated_closed.releases)<>1 THEN
  RAISE EXCEPTION 'Exact non-admitted clone required' USING ERRCODE='55000'; END IF;
 SELECT * INTO STRICT release FROM raa_authenticated_closed.releases;
 IF release.target_database IS DISTINCT FROM current_database()
  OR release.database_oid IS DISTINCT FROM (SELECT oid FROM pg_database WHERE datname=current_database())
  OR release.target_system IS DISTINCT FROM (SELECT system_identifier::text FROM pg_control_system()) OR release.admitted
  OR NOT EXISTS(SELECT FROM raa_closed_control.business_guard_releases r WHERE r.deployment_id=release.predecessor_id
   AND r.bundle_digest=release.predecessor_digest AND r.target_system=release.target_system
   AND r.target_database=release.target_database AND r.postmaster_start=release.postmaster_start
   AND r.checkpoint_id=release.checkpoint_id AND r.source_digest=release.source_digest
   AND r.baseline_digest=release.baseline_digest AND NOT r.admitted)
  OR (SELECT count(*) FROM raa_authenticated_closed.principals)<>16
  OR (SELECT count(*) FROM raa_authenticated_closed.principals WHERE kind='controller')<>1
  OR (SELECT count(*) FROM raa_authenticated_closed.principals WHERE kind='observer')<>1
  OR (SELECT count(*) FROM raa_authenticated_closed.principals WHERE kind='probe')<>14 THEN
  RAISE EXCEPTION 'Original clone binding required' USING ERRCODE='55000'; END IF;
 IF NOT EXISTS(SELECT FROM raa_authenticated_closed.principals p JOIN pg_roles r ON r.oid=p.role_oid
   WHERE r.rolname=session_user AND p.role_name=r.rolname AND p.kind IN ('controller','observer')) THEN
  RAISE EXCEPTION 'Exact authenticated control principal required' USING ERRCODE='55000'; END IF;
 FOR principal IN SELECT * FROM raa_authenticated_closed.principals LOOP
  SELECT * INTO role_record FROM pg_roles WHERE oid=principal.role_oid;
  IF NOT FOUND OR role_record.rolname IS DISTINCT FROM principal.role_name OR NOT role_record.rolcanlogin
   OR role_record.rolsuper OR role_record.rolcreatedb OR role_record.rolcreaterole OR role_record.rolreplication
   OR role_record.rolbypassrls OR role_record.rolinherit OR role_record.rolconfig IS NOT NULL
   OR EXISTS(SELECT FROM pg_auth_members WHERE roleid=principal.role_oid OR member=principal.role_oid)
   OR NOT has_database_privilege(principal.role_oid,current_database(),'CONNECT')
   OR has_database_privilege(principal.role_oid,current_database(),'CREATE,TEMPORARY')
   OR EXISTS(SELECT FROM pg_database WHERE datname<>current_database()
     AND has_database_privilege(principal.role_oid,oid,'CONNECT,CREATE,TEMPORARY'))
   OR NOT has_schema_privilege(principal.role_oid,
     CASE WHEN principal.kind='probe' THEN 'retail' ELSE 'raa_authenticated_closed' END,'USAGE')
   OR EXISTS(SELECT FROM pg_namespace WHERE starts_with(nspname,'raa_') OR nspname='retail'
     GROUP BY oid,nspname HAVING has_schema_privilege(principal.role_oid,oid,'USAGE')
      IS DISTINCT FROM (nspname=CASE WHEN principal.kind='probe' THEN 'retail' ELSE 'raa_authenticated_closed' END))
   OR EXISTS(SELECT FROM pg_database d CROSS JOIN LATERAL aclexplode(d.datacl) a
     WHERE a.grantee=principal.role_oid AND (d.datname<>current_database() OR a.is_grantable))
   OR EXISTS(SELECT FROM pg_namespace n CROSS JOIN LATERAL aclexplode(n.nspacl) a
     WHERE a.grantee=principal.role_oid AND (a.is_grantable OR a.privilege_type<>'USAGE'
       OR n.nspname<>CASE WHEN principal.kind='probe' THEN 'retail' ELSE 'raa_authenticated_closed' END))
   OR EXISTS(SELECT FROM pg_proc p CROSS JOIN LATERAL aclexplode(p.proacl) a
     WHERE a.grantee=principal.role_oid AND (a.is_grantable OR NOT (p.oid=ANY(principal.allowed_functions))))
   OR EXISTS(SELECT FROM pg_class c CROSS JOIN LATERAL aclexplode(c.relacl) a WHERE a.grantee=principal.role_oid)
   OR EXISTS(SELECT FROM pg_attribute c CROSS JOIN LATERAL aclexplode(c.attacl) a WHERE a.grantee=principal.role_oid)
   OR EXISTS(SELECT FROM pg_shdepend WHERE refclassid='pg_authid'::regclass
     AND refobjid=principal.role_oid AND deptype='o')
   OR EXISTS(SELECT FROM pg_database WHERE datdba=principal.role_oid)
   OR EXISTS(SELECT FROM pg_namespace WHERE nspowner=principal.role_oid OR
     has_schema_privilege(principal.role_oid,oid,'CREATE'))
   OR EXISTS(SELECT FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
     WHERE c.relowner=principal.role_oid OR (n.nspname !~ '^pg_' AND n.nspname<>'information_schema' AND
       ((c.relkind IN ('r','p','v','m','f') AND
         (has_table_privilege(principal.role_oid,c.oid,'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER,MAINTAIN')
          OR has_any_column_privilege(principal.role_oid,c.oid,'SELECT,INSERT,UPDATE,REFERENCES')))
        OR (c.relkind='S' AND has_sequence_privilege(principal.role_oid,c.oid,'USAGE,SELECT,UPDATE')))))
   OR EXISTS(SELECT FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
     WHERE p.proowner=principal.role_oid OR (n.nspname !~ '^pg_' AND n.nspname<>'information_schema'
       AND has_function_privilege(principal.role_oid,p.oid,'EXECUTE') IS DISTINCT FROM (p.oid=ANY(principal.allowed_functions))))
   OR EXISTS(SELECT FROM unnest(principal.allowed_functions) f(oid) LEFT JOIN pg_proc p ON p.oid=f.oid WHERE p.oid IS NULL) THEN
   RAISE EXCEPTION 'Exact principal rights required' USING ERRCODE='55000'; END IF;
 END LOOP;
 epoch_current:=release.postmaster_start=pg_postmaster_start_time();
 IF p_mutation AND (NOT epoch_current OR current_setting('transaction_isolation')<>'read committed'
   OR current_setting('transaction_read_only')<>'off'
   OR NOT EXISTS(SELECT FROM raa_authenticated_closed.principals WHERE role_name=session_user AND kind='controller')) THEN
  RAISE EXCEPTION 'Original current authenticated controller epoch required' USING ERRCODE='55000'; END IF;
 RETURN epoch_current;
END $body$;

CREATE FUNCTION raa_authenticated_closed.api_state_v1() RETURNS jsonb
LANGUAGE plpgsql VOLATILE PARALLEL UNSAFE CALLED ON NULL INPUT SECURITY DEFINER SET search_path=pg_catalog,raa_authenticated_closed AS $body$
DECLARE current_epoch boolean; result jsonb;
BEGIN
 current_epoch:=raa_authenticated_closed.check_target_v1(false);
 SELECT to_jsonb(l)||jsonb_build_object('epoch_current',current_epoch,'historical',NOT current_epoch,
  'caller_identity',raa_authenticated_closed.self_identity_v1(),
  'events',(SELECT count(*) FROM raa_authenticated_closed.events),'application_writers_admitted',false,
  'execution_authority',false) INTO STRICT result FROM raa_authenticated_closed.latch l WHERE singleton;
 RETURN result;
END $body$;

CREATE FUNCTION raa_authenticated_closed.api_claim_v1(p_claim_key uuid) RETURNS jsonb
LANGUAGE plpgsql VOLATILE PARALLEL UNSAFE CALLED ON NULL INPUT SECURITY DEFINER SET search_path=pg_catalog,raa_authenticated_closed AS $body$
DECLARE original raa_authenticated_closed.custody; own jsonb;
BEGIN
 PERFORM raa_authenticated_closed.check_target_v1(true);
 IF p_claim_key IS NULL THEN RAISE EXCEPTION 'Claim key required' USING ERRCODE='22023'; END IF;
 PERFORM 1 FROM raa_closed_control.latch WHERE singleton AND state='CLOSED' FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'Original CLOSED latch required' USING ERRCODE='55000'; END IF;
 PERFORM 1 FROM raa_authenticated_closed.latch WHERE singleton AND state='CLOSED' FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'Companion CLOSED latch required' USING ERRCODE='55000'; END IF;
 own:=raa_authenticated_closed.self_identity_v1();
 SELECT * INTO original FROM raa_authenticated_closed.custody WHERE singleton;
 IF FOUND THEN
  IF original.identity IS DISTINCT FROM own THEN
   RAISE EXCEPTION 'Original physical connection required; no takeover' USING ERRCODE='55000'; END IF;
  IF original.claim_key IS DISTINCT FROM p_claim_key THEN
   RAISE EXCEPTION 'Original claim binding required' USING ERRCODE='22023'; END IF;
  RETURN to_jsonb(original)||jsonb_build_object('execution_authority',false);
 END IF;
 IF own IS NULL OR EXISTS(SELECT FROM pg_prepared_xacts)
  OR EXISTS(SELECT FROM pg_stat_activity WHERE pid<>pg_backend_pid() AND backend_type NOT IN
    ('autovacuum launcher','autovacuum worker','background writer','checkpointer','walwriter','archiver','logical replication launcher')) THEN
  RAISE EXCEPTION 'Other connection or prepared transaction blocks claim' USING ERRCODE='55000'; END IF;
 INSERT INTO raa_authenticated_closed.custody(singleton,claim_key,identity,deployment_id)
  VALUES(true,p_claim_key,own,(SELECT deployment_id FROM raa_authenticated_closed.releases)) RETURNING * INTO original;
 RETURN to_jsonb(original)||jsonb_build_object('execution_authority',false);
END $body$;

CREATE FUNCTION raa_authenticated_closed.check_binding_v1(p_claim_key uuid,p_expected bigint,p_operation uuid,p_epoch uuid,p_digest text) RETURNS void
LANGUAGE plpgsql VOLATILE PARALLEL UNSAFE CALLED ON NULL INPUT SECURITY DEFINER SET search_path=pg_catalog,raa_authenticated_closed AS $body$
BEGIN
 IF p_claim_key IS NULL OR p_expected IS NULL OR p_expected<0 OR p_operation IS NULL OR p_epoch IS NULL
  OR p_digest IS NULL OR p_digest !~ '^[a-f0-9]{64}$' THEN
  RAISE EXCEPTION 'Exact operation binding required' USING ERRCODE='22023'; END IF;
END $body$;

CREATE FUNCTION raa_authenticated_closed.api_close_v1(p_claim_key uuid,p_expected bigint,p_operation uuid,p_epoch uuid,p_digest text) RETURNS jsonb
LANGUAGE plpgsql VOLATILE PARALLEL UNSAFE CALLED ON NULL INPUT SECURITY DEFINER SET search_path=pg_catalog,raa_authenticated_closed AS $body$
DECLARE original raa_authenticated_closed.custody; old raa_authenticated_closed.latch; saved raa_authenticated_closed.events;
BEGIN
 PERFORM raa_authenticated_closed.check_target_v1(true);
 PERFORM raa_authenticated_closed.check_binding_v1(p_claim_key,p_expected,p_operation,p_epoch,p_digest);
 PERFORM 1 FROM raa_closed_control.latch WHERE singleton AND state='CLOSED' FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'Original CLOSED latch required' USING ERRCODE='55000'; END IF;
 SELECT * INTO STRICT old FROM raa_authenticated_closed.latch WHERE singleton FOR UPDATE;
 SELECT * INTO original FROM raa_authenticated_closed.custody WHERE singleton;
 IF NOT FOUND OR original.identity IS DISTINCT FROM raa_authenticated_closed.self_identity_v1()
  OR original.claim_key IS DISTINCT FROM p_claim_key THEN
  RAISE EXCEPTION 'Original physical connection and claim required' USING ERRCODE='55000'; END IF;
 SELECT * INTO saved FROM raa_authenticated_closed.events WHERE operation_id=p_operation;
 IF FOUND THEN
  IF saved.claim_key IS DISTINCT FROM p_claim_key OR saved.previous_generation IS DISTINCT FROM p_expected
   OR saved.candidate_epoch IS DISTINCT FROM p_epoch OR saved.candidate_digest IS DISTINCT FROM p_digest THEN
   RAISE EXCEPTION 'Conflicting operation binding' USING ERRCODE='22023'; END IF;
  RETURN to_jsonb(saved)||jsonb_build_object('execution_authority',false);
 END IF;
 IF old.state<>'CLOSED' OR old.generation<>p_expected THEN
  RAISE EXCEPTION 'Stale CLOSED generation' USING ERRCODE='55000'; END IF;
 IF EXISTS(SELECT FROM raa_authenticated_closed.events WHERE candidate_epoch=p_epoch) THEN
  RAISE EXCEPTION 'Epoch already recorded' USING ERRCODE='22023'; END IF;
 INSERT INTO raa_authenticated_closed.events(operation_id,claim_key,previous_generation,generation,candidate_epoch,candidate_digest,state)
  VALUES(p_operation,p_claim_key,p_expected,p_expected+1,p_epoch,p_digest,'CLOSED') RETURNING * INTO saved;
 UPDATE raa_authenticated_closed.latch SET generation=saved.generation,operation_id=saved.operation_id WHERE singleton;
 RETURN to_jsonb(saved)||jsonb_build_object('execution_authority',false);
END $body$;

CREATE FUNCTION raa_authenticated_closed.api_reconcile_v1(p_claim_key uuid,p_expected bigint,p_operation uuid,p_epoch uuid,p_digest text) RETURNS jsonb
LANGUAGE plpgsql VOLATILE PARALLEL UNSAFE CALLED ON NULL INPUT SECURITY DEFINER SET search_path=pg_catalog,raa_authenticated_closed AS $body$
DECLARE current_epoch boolean; saved raa_authenticated_closed.events;
BEGIN
 current_epoch:=raa_authenticated_closed.check_target_v1(false);
 PERFORM raa_authenticated_closed.check_binding_v1(p_claim_key,p_expected,p_operation,p_epoch,p_digest);
 SELECT * INTO saved FROM raa_authenticated_closed.events WHERE operation_id=p_operation;
 IF NOT FOUND THEN RETURN NULL; END IF;
 IF saved.claim_key IS DISTINCT FROM p_claim_key OR saved.previous_generation IS DISTINCT FROM p_expected
  OR saved.candidate_epoch IS DISTINCT FROM p_epoch OR saved.candidate_digest IS DISTINCT FROM p_digest THEN
  RAISE EXCEPTION 'Conflicting reconciliation binding' USING ERRCODE='22023'; END IF;
 RETURN to_jsonb(saved)||jsonb_build_object('epoch_current',current_epoch,'historical',NOT current_epoch,'execution_authority',false);
END $body$;

CREATE FUNCTION raa_authenticated_closed.api_deny_runtime_v1() RETURNS void
LANGUAGE plpgsql VOLATILE PARALLEL UNSAFE CALLED ON NULL INPUT SECURITY DEFINER SET search_path=pg_catalog,raa_authenticated_closed AS $body$
BEGIN
 PERFORM raa_authenticated_closed.check_target_v1(false);
 PERFORM 1 FROM raa_closed_control.latch WHERE singleton FOR SHARE;
 RAISE EXCEPTION 'Runtime admission is not implemented' USING ERRCODE='55000';
END $body$;

REVOKE ALL ON ALL FUNCTIONS IN SCHEMA raa_authenticated_closed FROM PUBLIC;
INSERT INTO raa_authenticated_closed.releases(bundle_id,deployment_id,checkpoint_id,predecessor_id,predecessor_digest,
 source_digest,bundle_digest,baseline_digest,target_database,database_oid,target_system,postmaster_start)
 VALUES('wp4-rehearsal-007-authenticated-closed',current_setting('raa.deployment_id')::uuid,
 current_setting('raa.checkpoint_id')::uuid,current_setting('raa.predecessor_id')::uuid,current_setting('raa.predecessor_digest'),
 current_setting('raa.source_digest'),current_setting('raa.bundle_digest'),current_setting('raa.baseline_digest'),
 current_database(),(SELECT oid FROM pg_database WHERE datname=current_database()),
 current_setting('raa.rehearsal_system'),pg_postmaster_start_time());
INSERT INTO raa_authenticated_closed.latch VALUES(true,'CLOSED',0,NULL);
-- Role provisioning + exact direct grants + immutable principal rows must be in
-- this SAME transaction, using the reviewed bootstrap helper. Never execute alone.
