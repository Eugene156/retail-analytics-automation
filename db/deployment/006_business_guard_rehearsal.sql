-- Authored static clone006 deny-only caps. No original-body rewrite at runtime.
DO $guard$
DECLARE suffix text:=substring(current_database() from '^raa_wp4_populated_rehearsal_([a-f0-9]{12})$'); item record;
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
 IF to_regclass('raa_closed_control.custody_releases') IS NULL THEN
  RAISE EXCEPTION 'Committed deployment005 required'; END IF;
 IF NOT EXISTS(SELECT FROM raa_closed_control.custody_releases r
   WHERE r.bundle_id='wp4-rehearsal-005-custody' AND r.deployment_id=current_setting('raa.predecessor_id')::uuid
   AND r.bundle_digest=current_setting('raa.predecessor_digest')
   AND r.checkpoint_id=current_setting('raa.checkpoint_id')::uuid
   AND r.source_digest=current_setting('raa.source_digest') AND r.baseline_digest=current_setting('raa.baseline_digest')
   AND r.target_system=current_setting('raa.rehearsal_system') AND r.target_database=current_database()
   AND r.postmaster_start=pg_postmaster_start_time() AND r.base_version=20 AND NOT r.admitted)
  OR (SELECT count(*) FROM raa_closed_control.custody_releases)<>1
  OR (SELECT count(*) FROM raa_closed_control.custody)<>1
  OR to_regclass('raa_closed_control.business_guard_releases') IS NOT NULL
  OR NOT EXISTS(SELECT FROM raa_closed_control.latch l JOIN raa_closed_control.custody c USING(controller_id)
      WHERE l.singleton AND l.state='CLOSED' AND l.generation=(SELECT count(*) FROM raa_closed_control.events))
  OR (SELECT array_agg(version ORDER BY version) FROM retail.schema_migrations) IS DISTINCT FROM ARRAY(SELECT generate_series(1,20))
  OR EXISTS(SELECT FROM pg_prepared_xacts)
  OR EXISTS(SELECT FROM pg_stat_activity WHERE pid<>pg_backend_pid() AND backend_type NOT IN
      ('autovacuum launcher','autovacuum worker','background writer','checkpointer','walwriter','archiver','logical replication launcher'))
  OR EXISTS(SELECT FROM pg_roles WHERE (rolname='g0_user' OR starts_with(rolname,'raa_'))
      AND (rolcanlogin OR rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication OR rolbypassrls))
  OR EXISTS(SELECT FROM pg_auth_members m JOIN pg_roles a ON a.oid=m.roleid JOIN pg_roles b ON b.oid=m.member
      WHERE a.rolname='g0_user' OR b.rolname='g0_user' OR starts_with(a.rolname,'raa_') OR starts_with(b.rolname,'raa_')) THEN
  RAISE EXCEPTION 'Exact quiescent CLOSED005 predecessor required'; END IF;
 FOR item IN SELECT * FROM (VALUES
  ('retail.api_accept_portal_attempt_v1(uuid,text,uuid,text)','0708919dc561d006f8f7ce2b03dce0c7082a168dece951350fbae3613988cb88'),
  ('retail.api_accept_portal_publication_v2(uuid,text)','cc654837ecb6982000b7cc5b17e5c66fdb4481b7a0265746c71b4b2bb7360cf0'),
  ('retail.api_comparison_report_v1(text,timestamp,timestamp,timestamp)','2e0a6a415d3d5bd57a387643f315bc842aa465e5162bb5b4ded35d3b2105b8c9'),
  ('retail.api_current_approval_request_v2(uuid)','23c0eb8ea318dd968ced8defa6223cf19dc9fa532f49ca14294f589f9c9302e0'),
  ('retail.api_decide_portal_request_v2(text,text,uuid,text,text,text)','bb2f8555f0af6c72c421306335728d81513981cbf77c63a7aa572608c331719f'),
  ('retail.api_decide_request_v1(text,text,uuid,uuid,integer,text,text,text,text)','cd180d3c5fcc75986610dac313ac7a4f39e298575481670c2be0dbcc94bebb39'),
  ('retail.api_decision_snapshot_v1(text,uuid,uuid)','cb1da2ffa74c2860d846ec6443bc232399f7b7a1c5f2c2082ef3d20194e03e93'),
  ('retail.api_finish_report_v1(uuid)','adc3a259fbf0ad3a2e3af0e29ecbf46070817cbccc9ca86e6d2574c7e5e486c1'),
  ('retail.api_get_approval_proposal_v1(uuid)','3367aa24506e96253f8a3ec52d9ca999648bda69689634bf82ecaf528af43d61'),
  ('retail.api_get_approval_request_v2(uuid,uuid)','0ab7ffbc24cf03dc9385fcdc09b2e4eae4b2514d22ea2c6872b19f042adb18a2'),
  ('retail.api_get_case_v1(uuid)','8337632a28598112971056536123df939669b1f5153330571a48c37197163675'),
  ('retail.api_get_revision_v1(uuid,integer)','1e7dc5f119491269b46334a7220ef3e25465d75e7d8be2c9424bf9e69a995bd0'),
  ('retail.api_issue_approval_request_v2(uuid,integer,text,text,uuid)','a3ecd2fc912094c3533daa3fdb9d729dedb29e7ac115a8a1d3464d79c76bad31'),
  ('retail.api_issue_portal_request_v3(uuid,text,text,uuid)','eda6e0e9a176c108311193b7a38e9aeb4bbf1d5f2952de7db0537d4c88d83630'),
  ('retail.api_operator_reconcile_portal_v1(uuid,text,text)','44dbef9b05f8b68787d1db0240634395bc50a748682181c1fd9b2abae4270f04'),
  ('retail.api_owner_approval_request_v2(text,uuid,uuid)','e606809db3fa1b1281e9a9b4d5abe2619141210501a4394472a9c73cf5036666'),
  ('retail.api_owner_case_v1(text,uuid)','1595120bdb984255cb88922b75285194359c66b5d6d0c200b9319384c191bd91'),
  ('retail.api_owner_current_request_v2(text,uuid)','e3eec3b20f16532f16e0091702f1f12519c78c215ed5c482c9f19375b2d90c29'),
  ('retail.api_owner_decide_portal_request_v3(text,text,uuid,uuid,text,text,text,text)','42c8ab06628b6624840d3095c0cb039bf06b6d21d95ed6fc9c3ba70f0d00ff2c'),
  ('retail.api_owner_identity_v1(text)','d3afbb784a08ae76487429bdf8d457d0e1c5884a3f307a7012dcf87a65a46bc1'),
  ('retail.api_owner_portal_export_v2(text,uuid)','12e69c699429553a12569fcd32e3da43fbc2bd6467ccd4ee7f96ec8140d4449c'),
  ('retail.api_owner_portal_receipt_v2(text,uuid)','b4c071eb5f6aa4bc798271a022d3498b19ceb55dbeac0ad2f802d44656d2b7a9'),
  ('retail.api_owner_portal_request_v3(text,uuid)','87218cf4409d271abd537a1944a1441bda0d1f3c908fc13f88ef40826a770bf1'),
  ('retail.api_owner_portal_requests_v3(text)','e3602d979bfd86e9ef1bfaef74c05cc4c683317e11ec098b62deaea27cdf50b4'),
  ('retail.api_owner_portal_review_v3(text,uuid,uuid)','b997795e419ae97aa3961669e193f3e9ed77f4f758ed78be0d073eb5c2925e19'),
  ('retail.api_owner_portal_transition_v1(text,uuid)','6b0e1495709ccbea31cdc6f9dd5fd710f0076eb4660a3059a1c6e62398f97dff'),
  ('retail.api_owner_proposal_v1(text,uuid)','e569ce3dd23246cff06937f18025caf0c0e940d9049b84187ff933a3b5422a04'),
  ('retail.api_owner_retired_legacy_request_v1(text,uuid,uuid)','f2c90149d1ad69b3b2b33adc9d040cc6d4864e304a70f7255ee7738c0f7c3cfa'),
  ('retail.api_owner_revision_v1(text,uuid,integer)','3bfbc3c2d36d0a4899a65557ddb61d3b847812c12c721a1994bd1aaaa00a5d05'),
  ('retail.api_portal_attempt_state_v1(uuid,text)','a62348f0f0a5615a9f123783f41cd75e81db8ec7d38833cba62ced49c0d71a97'),
  ('retail.api_portal_auth_identity_v2(text)','120f18ce723909baea49269861842651e2fe119d4f4cb708dafa41e9c716520c'),
  ('retail.api_portal_auth_login_v2(text,text,text,text)','282b8078d8f5ec43d7009da5073419bd827a67397ba8c82a319c432fd69f85d4'),
  ('retail.api_portal_auth_logout_v2(text,text)','97c1bfe297a97ee7c34da4ff239043a66753977ea3eec37208d07fe80d3ac2ee'),
  ('retail.api_portal_case_v1(text,uuid)','e35e25d45dc88873070b87c44435c887eef39628e235dfd4b253f2b26116b87e'),
  ('retail.api_portal_identity_v1(text)','232eb981a3225c4b4069719419ecce242f1652e6e9c28118983f14cf886ba6e6'),
  ('retail.api_portal_login_v1(text,text,text,text)','1dfd45d55f2311641c11945a13288b166649f73b5fdd7fa1629f43adda7ada0f'),
  ('retail.api_portal_logout_v1(text,text)','5f6d88ba12a6f6b520e95adefaa9bfd41fbc55ec2c34e15d561b2775c3fa8544'),
  ('retail.api_portal_publication_state_v2(uuid)','87291e07d3f5d0453f1a09fb0571f8deee885ff0c8630e86fdc24e13dbd928e2'),
  ('retail.api_portal_request_v1(text,uuid,uuid)','9617cf74596e0b1aab6f8cd57f4e1d390a75337e1b980c8c7d1f8762ba1de7c9'),
  ('retail.api_portal_requests_v1(text)','fb78fe236b40c18a91a4c0143a206a116876504f49c83a0ae8df96f68092c96e'),
  ('retail.api_portal_revision_v1(text,uuid,integer)','a3b354226d64fae8cbb88df7fd345ccbf50847d9f33d053a9ce7b4c1f78cf188'),
  ('retail.api_portal_transition_state_v1(uuid,text)','4e44915a77c405a6ef3e157f32c524c69dcdc8af946945c5eb27a40d6d04c40b'),
  ('retail.api_reconcile_portal_attempt_v1(uuid,text)','bbee0f37a52d7da92add6247dcec6bd01076a638efc28d35649036a144b8803f'),
  ('retail.api_report_portal_attempt_v1(uuid,text,uuid,text,text)','9ad35ac3dbc5d30ec3806bda8e13d601fba5b78ef466e17444e73a20a8f30e83'),
  ('retail.api_reserve_portal_attempt_v1(uuid,text,uuid,text,text,text,text)','8a7198358264db065022f5b77b13b2d2763c13569bc3fe0490196eedf73b1250'),
  ('retail.api_reserve_report_v1(text,text,timestamp,timestamp,timestamp)','3b61cbbbe2b640f85ce2730d088b9d20555a968f9e1ff54faea3caa34eacf7f9'),
  ('retail.api_transition_legacy_portal_v1(uuid,uuid,text,text,text)','541e490ae4c29c6cb1ad998be2f88dba2f7c7bf207052e7293c3a78b958a536c'),
  ('retail.api_worker_accept_portal_v2(uuid,text,uuid,text,text)','75c31f974c8856fcad5ae292a194b977074c55ecfdc3eaa1b1d136806ced2f63'),
  ('retail.api_worker_portal_state_v2(uuid,text)','aeb05a5fd14861be623619eddc5b1ff7198fce177a5ddb9efc4713e705292a72')
 ) AS expected(signature,digest) LOOP
  IF NOT EXISTS(SELECT FROM pg_proc p WHERE p.oid=to_regprocedure(item.signature)
    AND pg_get_userbyid(p.proowner)='g0_user' AND p.prosecdef AND NOT p.proretset
    AND encode(sha256(convert_to(pg_get_functiondef(p.oid),'UTF8')),'hex')=item.digest) THEN
   RAISE EXCEPTION 'Exact original business function preimage required'; END IF;
 END LOOP;
 FOR item IN SELECT role_name,array_agg(signature ORDER BY signature COLLATE "C") AS signatures FROM (VALUES
  ('raa_wp4_portal_read_v2','api_portal_identity_v1(text)'),
  ('raa_wp4_portal_read_v2','api_owner_portal_request_v3(text,uuid)'),
  ('raa_wp4_portal_read_v2','api_owner_portal_receipt_v2(text,uuid)'),
  ('raa_wp4_portal_read_v2','api_owner_portal_export_v2(text,uuid)'),
  ('raa_wp4_portal_read_v2','api_owner_portal_review_v3(text,uuid,uuid)'),
  ('raa_wp4_portal_read_v2','api_owner_portal_requests_v3(text)'),
  ('raa_wp4_portal_read_v2','api_owner_portal_transition_v1(text,uuid)'),
  ('raa_wp4_portal_read_v2','api_owner_retired_legacy_request_v1(text,uuid,uuid)'),
  ('raa_wp4_portal_review_v2','api_decide_portal_request_v2(text,text,uuid,text,text,text)'),
  ('raa_wp4_portal_review_v2','api_owner_decide_portal_request_v3(text,text,uuid,uuid,text,text,text,text)'),
  ('raa_wp4_portal_issue_v3','api_issue_portal_request_v3(uuid,text,text,uuid)'),
  ('raa_wp4_portal_transition_v1','api_transition_legacy_portal_v1(uuid,uuid,text,text,text)'),
  ('raa_wp4_portal_transition_v1','api_portal_transition_state_v1(uuid,text)'),
  ('raa_wp4_portal_auth_v2','api_portal_auth_identity_v2(text)'),
  ('raa_wp4_portal_auth_v2','api_portal_auth_login_v2(text,text,text,text)'),
  ('raa_wp4_portal_auth_v2','api_portal_auth_logout_v2(text,text)'),
  ('raa_wp4_portal_attempt_v1','api_portal_attempt_state_v1(uuid,text)'),
  ('raa_wp4_portal_attempt_v1','api_reserve_portal_attempt_v1(uuid,text,uuid,text,text,text,text)'),
  ('raa_wp4_portal_attempt_v1','api_accept_portal_attempt_v1(uuid,text,uuid,text)'),
  ('raa_wp4_portal_attempt_v1','api_report_portal_attempt_v1(uuid,text,uuid,text,text)'),
  ('raa_wp4_portal_attempt_v1','api_reconcile_portal_attempt_v1(uuid,text)'),
  ('raa_wp4_portal_recovery_v1','api_operator_reconcile_portal_v1(uuid,text,text)'),
  ('raa_wp4_portal_publish_v2','api_accept_portal_publication_v2(uuid,text)'),
  ('raa_wp4_portal_publish_v2','api_portal_publication_state_v2(uuid)'),
  ('raa_wp4_portal_worker_v2','api_worker_portal_state_v2(uuid,text)'),
  ('raa_wp4_portal_worker_v2','api_worker_accept_portal_v2(uuid,text,uuid,text,text)'),
  ('raa_wp2_api','api_comparison_report_v1(text,timestamp,timestamp,timestamp)'),
  ('raa_wp2_case_api','api_reserve_report_v1(text,text,timestamp,timestamp,timestamp)'),
  ('raa_wp2_case_api','api_finish_report_v1(uuid)'),
  ('raa_wp2_case_api','api_get_case_v1(uuid)'),
  ('raa_wp2_case_api','api_get_revision_v1(uuid,integer)'),
  ('raa_wp2_case_api','api_get_approval_proposal_v1(uuid)'),
  ('raa_wp2_case_api','api_get_approval_request_v2(uuid,uuid)'),
  ('raa_wp2_case_api','api_current_approval_request_v2(uuid)'),
  ('raa_wp2_case_api','api_issue_approval_request_v2(uuid,integer,text,text,uuid)'),
  ('raa_wp4_reviewer_api','api_owner_identity_v1(text)'),
  ('raa_wp4_reviewer_api','api_owner_case_v1(text,uuid)'),
  ('raa_wp4_reviewer_api','api_owner_revision_v1(text,uuid,integer)'),
  ('raa_wp4_reviewer_api','api_owner_proposal_v1(text,uuid)'),
  ('raa_wp4_reviewer_api','api_owner_approval_request_v2(text,uuid,uuid)'),
  ('raa_wp4_reviewer_api','api_owner_current_request_v2(text,uuid)'),
  ('raa_wp4_portal_api','api_portal_identity_v1(text)'),
  ('raa_wp4_portal_api','api_portal_login_v1(text,text,text,text)'),
  ('raa_wp4_portal_api','api_portal_logout_v1(text,text)'),
  ('raa_wp4_portal_api','api_portal_requests_v1(text)'),
  ('raa_wp4_portal_api','api_portal_request_v1(text,uuid,uuid)'),
  ('raa_wp4_portal_api','api_portal_case_v1(text,uuid)'),
  ('raa_wp4_portal_api','api_portal_revision_v1(text,uuid,integer)'),
  ('raa_wp4_portal_api','api_decide_request_v1(text,text,uuid,uuid,integer,text,text,text,text)'),
  ('raa_wp4_portal_api','api_decision_snapshot_v1(text,uuid,uuid)'),
  ('raa_wp4_decision_api','api_decide_request_v1(text,text,uuid,uuid,integer,text,text,text,text)'),
  ('raa_wp4_decision_api','api_decision_snapshot_v1(text,uuid,uuid)')
 ) AS expected(role_name,signature) GROUP BY role_name LOOP
  IF ARRAY(SELECT replace(replace(p.proname||'('||oidvectortypes(p.proargtypes)||')','timestamp without time zone','timestamp'),' ','')
     FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='retail'
     AND has_function_privilege(item.role_name,p.oid,'EXECUTE') ORDER BY p.proname,oidvectortypes(p.proargtypes))
     IS DISTINCT FROM item.signatures
   OR has_database_privilege(item.role_name,current_database(),'CREATE,TEMP')
   OR has_schema_privilege(item.role_name,'raa_closed_control','USAGE')
   OR EXISTS(SELECT FROM pg_namespace WHERE nspname IN ('public','retail','raa_closed_control','raa_deployment')
      AND has_schema_privilege(item.role_name,oid,'CREATE')) THEN
   RAISE EXCEPTION 'Exact fourteen scoped caller roles required'; END IF;
 END LOOP;
 IF EXISTS(SELECT FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace,
    LATERAL aclexplode(coalesce(p.proacl,acldefault('f',p.proowner))) a
    WHERE n.nspname='retail' AND a.grantee=0 AND a.privilege_type='EXECUTE') THEN
  RAISE EXCEPTION 'PUBLIC business EXECUTE denied'; END IF;
END $guard$;

CREATE TABLE raa_closed_control.business_guard_releases (
 bundle_id text PRIMARY KEY CHECK(bundle_id='wp4-rehearsal-006-business-closed'),
 deployment_id uuid NOT NULL UNIQUE, checkpoint_id uuid NOT NULL,
 predecessor_id uuid NOT NULL REFERENCES raa_closed_control.custody_releases(deployment_id),
 predecessor_digest text NOT NULL CHECK(predecessor_digest ~ '^[a-f0-9]{64}$'),
 source_digest text NOT NULL CHECK(source_digest ~ '^[a-f0-9]{64}$'),
 bundle_digest text NOT NULL CHECK(bundle_digest ~ '^[a-f0-9]{64}$'),
 baseline_digest text NOT NULL CHECK(baseline_digest ~ '^[a-f0-9]{64}$'),
 base_version integer NOT NULL CHECK(base_version=20),
 target_database name NOT NULL,target_system text NOT NULL,
 postmaster_start timestamptz NOT NULL CHECK(isfinite(postmaster_start)),
 installed_at timestamptz NOT NULL CHECK(isfinite(installed_at)),
 admitted boolean NOT NULL DEFAULT false CHECK(admitted=false)
);
REVOKE ALL ON raa_closed_control.business_guard_releases FROM PUBLIC;
CREATE TRIGGER immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON raa_closed_control.business_guard_releases
 FOR EACH STATEMENT EXECUTE FUNCTION raa_closed_control.reject_mutation_v1();

CREATE FUNCTION raa_closed_control.guard_business_closed_v1() RETURNS void
LANGUAGE plpgsql VOLATILE PARALLEL UNSAFE CALLED ON NULL INPUT SECURITY DEFINER
SET search_path=pg_catalog,raa_closed_control AS $body$
BEGIN
 IF current_setting('transaction_isolation')<>'read committed' OR current_setting('transaction_read_only')<>'off' THEN
  RAISE EXCEPTION 'READ COMMITTED READ WRITE required' USING ERRCODE='55000'; END IF;
 PERFORM 1 FROM raa_closed_control.latch WHERE singleton FOR SHARE;
 PERFORM raa_closed_control.check_custody_target_v1();
 IF NOT EXISTS(SELECT FROM raa_closed_control.business_guard_releases r WHERE NOT r.admitted
   AND r.target_database=current_database() AND r.target_system=(SELECT system_identifier::text FROM pg_control_system())
   AND r.postmaster_start=pg_postmaster_start_time()) THEN
  RAISE EXCEPTION 'Original CLOSED guard release required' USING ERRCODE='55000'; END IF;
 RAISE EXCEPTION 'CLOSED business entry denied' USING ERRCODE='55000';
END $body$;
REVOKE ALL ON FUNCTION raa_closed_control.guard_business_closed_v1() FROM PUBLIC;
-- Only the existing definer owner, NOT the fourteen scoped caller roles.
GRANT USAGE ON SCHEMA raa_closed_control TO g0_user;
GRANT EXECUTE ON FUNCTION raa_closed_control.guard_business_closed_v1() TO g0_user;

CREATE OR REPLACE FUNCTION retail.api_accept_portal_attempt_v1(p_action uuid, p_key text, p_attempt uuid, p_execution text) RETURNS text
LANGUAGE plpgsql VOLATILE PARALLEL UNSAFE CALLED ON NULL INPUT SECURITY DEFINER
SET search_path=pg_catalog,retail AS $cap$
BEGIN
 PERFORM raa_closed_control.guard_business_closed_v1();
 RAISE EXCEPTION 'CLOSED business entry denied' USING ERRCODE='55000';
END $cap$;

CREATE OR REPLACE FUNCTION retail.api_accept_portal_publication_v2(p_action uuid, p_key text) RETURNS text
LANGUAGE plpgsql VOLATILE PARALLEL UNSAFE CALLED ON NULL INPUT SECURITY DEFINER
SET search_path=pg_catalog,retail AS $cap$
BEGIN
 PERFORM raa_closed_control.guard_business_closed_v1();
 RAISE EXCEPTION 'CLOSED business entry denied' USING ERRCODE='55000';
END $cap$;

CREATE OR REPLACE FUNCTION retail.api_comparison_report_v1(p_source_file_sha256 text, p_start_inclusive timestamp without time zone, p_end_exclusive timestamp without time zone, p_source_as_of_exclusive timestamp without time zone) RETURNS text
LANGUAGE plpgsql VOLATILE PARALLEL UNSAFE CALLED ON NULL INPUT SECURITY DEFINER
SET search_path=pg_catalog,retail AS $cap$
BEGIN
 PERFORM raa_closed_control.guard_business_closed_v1();
 RAISE EXCEPTION 'CLOSED business entry denied' USING ERRCODE='55000';
END $cap$;

CREATE OR REPLACE FUNCTION retail.api_current_approval_request_v2(p_case uuid) RETURNS text
LANGUAGE plpgsql VOLATILE PARALLEL UNSAFE CALLED ON NULL INPUT SECURITY DEFINER
SET search_path=pg_catalog,retail AS $cap$
BEGIN
 PERFORM raa_closed_control.guard_business_closed_v1();
 RAISE EXCEPTION 'CLOSED business entry denied' USING ERRCODE='55000';
END $cap$;

CREATE OR REPLACE FUNCTION retail.api_decide_portal_request_v2(p_session text, p_csrf text, p_request uuid, p_hash text, p_choice text, p_key text) RETURNS text
LANGUAGE plpgsql VOLATILE PARALLEL UNSAFE CALLED ON NULL INPUT SECURITY DEFINER
SET search_path=pg_catalog,retail AS $cap$
BEGIN
 PERFORM raa_closed_control.guard_business_closed_v1();
 RAISE EXCEPTION 'CLOSED business entry denied' USING ERRCODE='55000';
END $cap$;

CREATE OR REPLACE FUNCTION retail.api_decide_request_v1(p_session text, p_csrf text, p_case uuid, p_proposal uuid, p_revision integer, p_report_hash text, p_proposal_hash text, p_choice text, p_key text) RETURNS text
LANGUAGE plpgsql VOLATILE PARALLEL UNSAFE CALLED ON NULL INPUT SECURITY DEFINER
SET search_path=pg_catalog,retail SET timezone='UTC' AS $cap$
BEGIN
 PERFORM raa_closed_control.guard_business_closed_v1();
 RAISE EXCEPTION 'CLOSED business entry denied' USING ERRCODE='55000';
END $cap$;

CREATE OR REPLACE FUNCTION retail.api_decision_snapshot_v1(p_session text, p_case uuid, p_proposal uuid) RETURNS text
LANGUAGE plpgsql VOLATILE PARALLEL UNSAFE CALLED ON NULL INPUT SECURITY DEFINER
SET search_path=pg_catalog,retail AS $cap$
BEGIN
 PERFORM raa_closed_control.guard_business_closed_v1();
 RAISE EXCEPTION 'CLOSED business entry denied' USING ERRCODE='55000';
END $cap$;

CREATE OR REPLACE FUNCTION retail.api_finish_report_v1(p_case_id uuid) RETURNS text
LANGUAGE plpgsql VOLATILE PARALLEL UNSAFE CALLED ON NULL INPUT SECURITY DEFINER
SET search_path=pg_catalog,retail AS $cap$
BEGIN
 PERFORM raa_closed_control.guard_business_closed_v1();
 RAISE EXCEPTION 'CLOSED business entry denied' USING ERRCODE='55000';
END $cap$;

CREATE OR REPLACE FUNCTION retail.api_get_approval_proposal_v1(p_case_id uuid) RETURNS text
LANGUAGE plpgsql VOLATILE PARALLEL UNSAFE CALLED ON NULL INPUT SECURITY DEFINER
SET search_path=pg_catalog,retail SET timezone='UTC' AS $cap$
BEGIN
 PERFORM raa_closed_control.guard_business_closed_v1();
 RAISE EXCEPTION 'CLOSED business entry denied' USING ERRCODE='55000';
END $cap$;

CREATE OR REPLACE FUNCTION retail.api_get_approval_request_v2(p_case uuid, p_id uuid) RETURNS text
LANGUAGE plpgsql VOLATILE PARALLEL UNSAFE CALLED ON NULL INPUT SECURITY DEFINER
SET search_path=pg_catalog,retail SET timezone='UTC' AS $cap$
BEGIN
 PERFORM raa_closed_control.guard_business_closed_v1();
 RAISE EXCEPTION 'CLOSED business entry denied' USING ERRCODE='55000';
END $cap$;

CREATE OR REPLACE FUNCTION retail.api_get_case_v1(p_case_id uuid) RETURNS text
LANGUAGE plpgsql VOLATILE PARALLEL UNSAFE CALLED ON NULL INPUT SECURITY DEFINER
SET search_path=pg_catalog,retail AS $cap$
BEGIN
 PERFORM raa_closed_control.guard_business_closed_v1();
 RAISE EXCEPTION 'CLOSED business entry denied' USING ERRCODE='55000';
END $cap$;

CREATE OR REPLACE FUNCTION retail.api_get_revision_v1(p_case_id uuid, p_revision integer) RETURNS text
LANGUAGE plpgsql VOLATILE PARALLEL UNSAFE CALLED ON NULL INPUT SECURITY DEFINER
SET search_path=pg_catalog,retail AS $cap$
BEGIN
 PERFORM raa_closed_control.guard_business_closed_v1();
 RAISE EXCEPTION 'CLOSED business entry denied' USING ERRCODE='55000';
END $cap$;

CREATE OR REPLACE FUNCTION retail.api_issue_approval_request_v2(p_case uuid, p_revision integer, p_hash text, p_key text, p_predecessor uuid) RETURNS text
LANGUAGE plpgsql VOLATILE PARALLEL UNSAFE CALLED ON NULL INPUT SECURITY DEFINER
SET search_path=pg_catalog,retail SET timezone='UTC' AS $cap$
BEGIN
 PERFORM raa_closed_control.guard_business_closed_v1();
 RAISE EXCEPTION 'CLOSED business entry denied' USING ERRCODE='55000';
END $cap$;

CREATE OR REPLACE FUNCTION retail.api_issue_portal_request_v3(p_case uuid, p_hash text, p_key text, p_parent uuid) RETURNS text
LANGUAGE plpgsql VOLATILE PARALLEL UNSAFE CALLED ON NULL INPUT SECURITY DEFINER
SET search_path=pg_catalog,retail AS $cap$
BEGIN
 PERFORM raa_closed_control.guard_business_closed_v1();
 RAISE EXCEPTION 'CLOSED business entry denied' USING ERRCODE='55000';
END $cap$;

CREATE OR REPLACE FUNCTION retail.api_operator_reconcile_portal_v1(p_action uuid, p_key text, p_recovery text) RETURNS text
LANGUAGE plpgsql VOLATILE PARALLEL UNSAFE CALLED ON NULL INPUT SECURITY DEFINER
SET search_path=pg_catalog,retail AS $cap$
BEGIN
 PERFORM raa_closed_control.guard_business_closed_v1();
 RAISE EXCEPTION 'CLOSED business entry denied' USING ERRCODE='55000';
END $cap$;

CREATE OR REPLACE FUNCTION retail.api_owner_approval_request_v2(p_digest text, p_case uuid, p_id uuid) RETURNS text
LANGUAGE plpgsql VOLATILE PARALLEL UNSAFE CALLED ON NULL INPUT SECURITY DEFINER
SET search_path=pg_catalog,retail AS $cap$
BEGIN
 PERFORM raa_closed_control.guard_business_closed_v1();
 RAISE EXCEPTION 'CLOSED business entry denied' USING ERRCODE='55000';
END $cap$;

CREATE OR REPLACE FUNCTION retail.api_owner_case_v1(p_digest text, p_case_id uuid) RETURNS text
LANGUAGE plpgsql VOLATILE PARALLEL UNSAFE CALLED ON NULL INPUT SECURITY DEFINER
SET search_path=pg_catalog,retail AS $cap$
BEGIN
 PERFORM raa_closed_control.guard_business_closed_v1();
 RAISE EXCEPTION 'CLOSED business entry denied' USING ERRCODE='55000';
END $cap$;

CREATE OR REPLACE FUNCTION retail.api_owner_current_request_v2(p_digest text, p_case uuid) RETURNS text
LANGUAGE plpgsql VOLATILE PARALLEL UNSAFE CALLED ON NULL INPUT SECURITY DEFINER
SET search_path=pg_catalog,retail AS $cap$
BEGIN
 PERFORM raa_closed_control.guard_business_closed_v1();
 RAISE EXCEPTION 'CLOSED business entry denied' USING ERRCODE='55000';
END $cap$;

CREATE OR REPLACE FUNCTION retail.api_owner_decide_portal_request_v3(p_session text, p_csrf text, p_case uuid, p_request uuid, p_report_hash text, p_request_hash text, p_choice text, p_key text) RETURNS text
LANGUAGE plpgsql VOLATILE PARALLEL UNSAFE CALLED ON NULL INPUT SECURITY DEFINER
SET search_path=pg_catalog,retail AS $cap$
BEGIN
 PERFORM raa_closed_control.guard_business_closed_v1();
 RAISE EXCEPTION 'CLOSED business entry denied' USING ERRCODE='55000';
END $cap$;

CREATE OR REPLACE FUNCTION retail.api_owner_identity_v1(p_digest text) RETURNS uuid
LANGUAGE plpgsql VOLATILE PARALLEL UNSAFE CALLED ON NULL INPUT SECURITY DEFINER
SET search_path=pg_catalog,retail AS $cap$
BEGIN
 PERFORM raa_closed_control.guard_business_closed_v1();
 RAISE EXCEPTION 'CLOSED business entry denied' USING ERRCODE='55000';
END $cap$;

CREATE OR REPLACE FUNCTION retail.api_owner_portal_export_v2(p_session text, p_action uuid) RETURNS text
LANGUAGE plpgsql VOLATILE PARALLEL UNSAFE CALLED ON NULL INPUT SECURITY DEFINER
SET search_path=pg_catalog,retail AS $cap$
BEGIN
 PERFORM raa_closed_control.guard_business_closed_v1();
 RAISE EXCEPTION 'CLOSED business entry denied' USING ERRCODE='55000';
END $cap$;

CREATE OR REPLACE FUNCTION retail.api_owner_portal_receipt_v2(p_session text, p_action uuid) RETURNS text
LANGUAGE plpgsql VOLATILE PARALLEL UNSAFE CALLED ON NULL INPUT SECURITY DEFINER
SET search_path=pg_catalog,retail AS $cap$
BEGIN
 PERFORM raa_closed_control.guard_business_closed_v1();
 RAISE EXCEPTION 'CLOSED business entry denied' USING ERRCODE='55000';
END $cap$;

CREATE OR REPLACE FUNCTION retail.api_owner_portal_request_v3(p_session text, p_request uuid) RETURNS text
LANGUAGE plpgsql VOLATILE PARALLEL UNSAFE CALLED ON NULL INPUT SECURITY DEFINER
SET search_path=pg_catalog,retail AS $cap$
BEGIN
 PERFORM raa_closed_control.guard_business_closed_v1();
 RAISE EXCEPTION 'CLOSED business entry denied' USING ERRCODE='55000';
END $cap$;

CREATE OR REPLACE FUNCTION retail.api_owner_portal_requests_v3(p_session text) RETURNS text
LANGUAGE plpgsql VOLATILE PARALLEL UNSAFE CALLED ON NULL INPUT SECURITY DEFINER
SET search_path=pg_catalog,retail SET timezone='UTC' AS $cap$
BEGIN
 PERFORM raa_closed_control.guard_business_closed_v1();
 RAISE EXCEPTION 'CLOSED business entry denied' USING ERRCODE='55000';
END $cap$;

CREATE OR REPLACE FUNCTION retail.api_owner_portal_review_v3(p_session text, p_case uuid, p_request uuid) RETURNS text
LANGUAGE plpgsql VOLATILE PARALLEL UNSAFE CALLED ON NULL INPUT SECURITY DEFINER
SET search_path=pg_catalog,retail AS $cap$
BEGIN
 PERFORM raa_closed_control.guard_business_closed_v1();
 RAISE EXCEPTION 'CLOSED business entry denied' USING ERRCODE='55000';
END $cap$;

CREATE OR REPLACE FUNCTION retail.api_owner_portal_transition_v1(p_session text, p_case uuid) RETURNS text
LANGUAGE plpgsql VOLATILE PARALLEL UNSAFE CALLED ON NULL INPUT SECURITY DEFINER
SET search_path=pg_catalog,retail AS $cap$
BEGIN
 PERFORM raa_closed_control.guard_business_closed_v1();
 RAISE EXCEPTION 'CLOSED business entry denied' USING ERRCODE='55000';
END $cap$;

CREATE OR REPLACE FUNCTION retail.api_owner_proposal_v1(p_digest text, p_case_id uuid) RETURNS text
LANGUAGE plpgsql VOLATILE PARALLEL UNSAFE CALLED ON NULL INPUT SECURITY DEFINER
SET search_path=pg_catalog,retail AS $cap$
BEGIN
 PERFORM raa_closed_control.guard_business_closed_v1();
 RAISE EXCEPTION 'CLOSED business entry denied' USING ERRCODE='55000';
END $cap$;

CREATE OR REPLACE FUNCTION retail.api_owner_retired_legacy_request_v1(p_session text, p_case uuid, p_old uuid) RETURNS text
LANGUAGE plpgsql VOLATILE PARALLEL UNSAFE CALLED ON NULL INPUT SECURITY DEFINER
SET search_path=pg_catalog,retail SET timezone='UTC' AS $cap$
BEGIN
 PERFORM raa_closed_control.guard_business_closed_v1();
 RAISE EXCEPTION 'CLOSED business entry denied' USING ERRCODE='55000';
END $cap$;

CREATE OR REPLACE FUNCTION retail.api_owner_revision_v1(p_digest text, p_case_id uuid, p_revision integer) RETURNS text
LANGUAGE plpgsql VOLATILE PARALLEL UNSAFE CALLED ON NULL INPUT SECURITY DEFINER
SET search_path=pg_catalog,retail AS $cap$
BEGIN
 PERFORM raa_closed_control.guard_business_closed_v1();
 RAISE EXCEPTION 'CLOSED business entry denied' USING ERRCODE='55000';
END $cap$;

CREATE OR REPLACE FUNCTION retail.api_portal_attempt_state_v1(p_action uuid, p_key text) RETURNS text
LANGUAGE plpgsql VOLATILE PARALLEL UNSAFE CALLED ON NULL INPUT SECURITY DEFINER
SET search_path=pg_catalog,retail AS $cap$
BEGIN
 PERFORM raa_closed_control.guard_business_closed_v1();
 RAISE EXCEPTION 'CLOSED business entry denied' USING ERRCODE='55000';
END $cap$;

CREATE OR REPLACE FUNCTION retail.api_portal_auth_identity_v2(p_session text) RETURNS uuid
LANGUAGE plpgsql VOLATILE PARALLEL UNSAFE CALLED ON NULL INPUT SECURITY DEFINER
SET search_path=pg_catalog,retail AS $cap$
BEGIN
 PERFORM raa_closed_control.guard_business_closed_v1();
 RAISE EXCEPTION 'CLOSED business entry denied' USING ERRCODE='55000';
END $cap$;

CREATE OR REPLACE FUNCTION retail.api_portal_auth_login_v2(p_owner text, p_session text, p_csrf text, p_old text) RETURNS text
LANGUAGE plpgsql VOLATILE PARALLEL UNSAFE CALLED ON NULL INPUT SECURITY DEFINER
SET search_path=pg_catalog,retail SET timezone='UTC' AS $cap$
BEGIN
 PERFORM raa_closed_control.guard_business_closed_v1();
 RAISE EXCEPTION 'CLOSED business entry denied' USING ERRCODE='55000';
END $cap$;

CREATE OR REPLACE FUNCTION retail.api_portal_auth_logout_v2(p_session text, p_csrf text) RETURNS boolean
LANGUAGE plpgsql VOLATILE PARALLEL UNSAFE CALLED ON NULL INPUT SECURITY DEFINER
SET search_path=pg_catalog,retail AS $cap$
BEGIN
 PERFORM raa_closed_control.guard_business_closed_v1();
 RAISE EXCEPTION 'CLOSED business entry denied' USING ERRCODE='55000';
END $cap$;

CREATE OR REPLACE FUNCTION retail.api_portal_case_v1(p_session text, p_case uuid) RETURNS text
LANGUAGE plpgsql VOLATILE PARALLEL UNSAFE CALLED ON NULL INPUT SECURITY DEFINER
SET search_path=pg_catalog,retail AS $cap$
BEGIN
 PERFORM raa_closed_control.guard_business_closed_v1();
 RAISE EXCEPTION 'CLOSED business entry denied' USING ERRCODE='55000';
END $cap$;

CREATE OR REPLACE FUNCTION retail.api_portal_identity_v1(p_session text) RETURNS uuid
LANGUAGE plpgsql VOLATILE PARALLEL UNSAFE CALLED ON NULL INPUT SECURITY DEFINER
SET search_path=pg_catalog,retail AS $cap$
BEGIN
 PERFORM raa_closed_control.guard_business_closed_v1();
 RAISE EXCEPTION 'CLOSED business entry denied' USING ERRCODE='55000';
END $cap$;

CREATE OR REPLACE FUNCTION retail.api_portal_login_v1(p_owner text, p_session text, p_csrf text, p_old text) RETURNS uuid
LANGUAGE plpgsql VOLATILE PARALLEL UNSAFE CALLED ON NULL INPUT SECURITY DEFINER
SET search_path=pg_catalog,retail AS $cap$
BEGIN
 PERFORM raa_closed_control.guard_business_closed_v1();
 RAISE EXCEPTION 'CLOSED business entry denied' USING ERRCODE='55000';
END $cap$;

CREATE OR REPLACE FUNCTION retail.api_portal_logout_v1(p_session text, p_csrf text) RETURNS boolean
LANGUAGE plpgsql VOLATILE PARALLEL UNSAFE CALLED ON NULL INPUT SECURITY DEFINER
SET search_path=pg_catalog,retail AS $cap$
BEGIN
 PERFORM raa_closed_control.guard_business_closed_v1();
 RAISE EXCEPTION 'CLOSED business entry denied' USING ERRCODE='55000';
END $cap$;

CREATE OR REPLACE FUNCTION retail.api_portal_publication_state_v2(p_action uuid) RETURNS text
LANGUAGE plpgsql VOLATILE PARALLEL UNSAFE CALLED ON NULL INPUT SECURITY DEFINER
SET search_path=pg_catalog,retail AS $cap$
BEGIN
 PERFORM raa_closed_control.guard_business_closed_v1();
 RAISE EXCEPTION 'CLOSED business entry denied' USING ERRCODE='55000';
END $cap$;

CREATE OR REPLACE FUNCTION retail.api_portal_request_v1(p_session text, p_case uuid, p_id uuid) RETURNS text
LANGUAGE plpgsql VOLATILE PARALLEL UNSAFE CALLED ON NULL INPUT SECURITY DEFINER
SET search_path=pg_catalog,retail AS $cap$
BEGIN
 PERFORM raa_closed_control.guard_business_closed_v1();
 RAISE EXCEPTION 'CLOSED business entry denied' USING ERRCODE='55000';
END $cap$;

CREATE OR REPLACE FUNCTION retail.api_portal_requests_v1(p_session text) RETURNS text
LANGUAGE plpgsql VOLATILE PARALLEL UNSAFE CALLED ON NULL INPUT SECURITY DEFINER
SET search_path=pg_catalog,retail SET timezone='UTC' AS $cap$
BEGIN
 PERFORM raa_closed_control.guard_business_closed_v1();
 RAISE EXCEPTION 'CLOSED business entry denied' USING ERRCODE='55000';
END $cap$;

CREATE OR REPLACE FUNCTION retail.api_portal_revision_v1(p_session text, p_case uuid, p_revision integer) RETURNS text
LANGUAGE plpgsql VOLATILE PARALLEL UNSAFE CALLED ON NULL INPUT SECURITY DEFINER
SET search_path=pg_catalog,retail AS $cap$
BEGIN
 PERFORM raa_closed_control.guard_business_closed_v1();
 RAISE EXCEPTION 'CLOSED business entry denied' USING ERRCODE='55000';
END $cap$;

CREATE OR REPLACE FUNCTION retail.api_portal_transition_state_v1(p_case uuid, p_key text) RETURNS text
LANGUAGE plpgsql VOLATILE PARALLEL UNSAFE CALLED ON NULL INPUT SECURITY DEFINER
SET search_path=pg_catalog,retail AS $cap$
BEGIN
 PERFORM raa_closed_control.guard_business_closed_v1();
 RAISE EXCEPTION 'CLOSED business entry denied' USING ERRCODE='55000';
END $cap$;

CREATE OR REPLACE FUNCTION retail.api_reconcile_portal_attempt_v1(p_action uuid, p_key text) RETURNS text
LANGUAGE plpgsql VOLATILE PARALLEL UNSAFE CALLED ON NULL INPUT SECURITY DEFINER
SET search_path=pg_catalog,retail AS $cap$
BEGIN
 PERFORM raa_closed_control.guard_business_closed_v1();
 RAISE EXCEPTION 'CLOSED business entry denied' USING ERRCODE='55000';
END $cap$;

CREATE OR REPLACE FUNCTION retail.api_report_portal_attempt_v1(p_action uuid, p_key text, p_attempt uuid, p_execution text, p_outcome text) RETURNS text
LANGUAGE plpgsql VOLATILE PARALLEL UNSAFE CALLED ON NULL INPUT SECURITY DEFINER
SET search_path=pg_catalog,retail AS $cap$
BEGIN
 PERFORM raa_closed_control.guard_business_closed_v1();
 RAISE EXCEPTION 'CLOSED business entry denied' USING ERRCODE='55000';
END $cap$;

CREATE OR REPLACE FUNCTION retail.api_reserve_portal_attempt_v1(p_action uuid, p_key text, p_case uuid, p_request_sha text, p_report_sha text, p_attempt_key text, p_execution text) RETURNS text
LANGUAGE plpgsql VOLATILE PARALLEL UNSAFE CALLED ON NULL INPUT SECURITY DEFINER
SET search_path=pg_catalog,retail AS $cap$
BEGIN
 PERFORM raa_closed_control.guard_business_closed_v1();
 RAISE EXCEPTION 'CLOSED business entry denied' USING ERRCODE='55000';
END $cap$;

CREATE OR REPLACE FUNCTION retail.api_reserve_report_v1(p_key text, p_hash text, p_start timestamp without time zone, p_end timestamp without time zone, p_asof timestamp without time zone) RETURNS text
LANGUAGE plpgsql VOLATILE PARALLEL UNSAFE CALLED ON NULL INPUT SECURITY DEFINER
SET search_path=pg_catalog,retail AS $cap$
BEGIN
 PERFORM raa_closed_control.guard_business_closed_v1();
 RAISE EXCEPTION 'CLOSED business entry denied' USING ERRCODE='55000';
END $cap$;

CREATE OR REPLACE FUNCTION retail.api_transition_legacy_portal_v1(p_case uuid, p_old uuid, p_old_hash text, p_report_hash text, p_key text) RETURNS text
LANGUAGE plpgsql VOLATILE PARALLEL UNSAFE CALLED ON NULL INPUT SECURITY DEFINER
SET search_path=pg_catalog,retail SET timezone='UTC' AS $cap$
BEGIN
 PERFORM raa_closed_control.guard_business_closed_v1();
 RAISE EXCEPTION 'CLOSED business entry denied' USING ERRCODE='55000';
END $cap$;

CREATE OR REPLACE FUNCTION retail.api_worker_accept_portal_v2(p_action uuid, p_key text, p_case uuid, p_request_sha text, p_report_sha text) RETURNS text
LANGUAGE plpgsql VOLATILE PARALLEL UNSAFE CALLED ON NULL INPUT SECURITY DEFINER
SET search_path=pg_catalog,retail AS $cap$
BEGIN
 PERFORM raa_closed_control.guard_business_closed_v1();
 RAISE EXCEPTION 'CLOSED business entry denied' USING ERRCODE='55000';
END $cap$;

CREATE OR REPLACE FUNCTION retail.api_worker_portal_state_v2(p_action uuid, p_key text) RETURNS text
LANGUAGE plpgsql VOLATILE PARALLEL UNSAFE CALLED ON NULL INPUT SECURITY DEFINER
SET search_path=pg_catalog,retail SET timezone='UTC' AS $cap$
BEGIN
 PERFORM raa_closed_control.guard_business_closed_v1();
 RAISE EXCEPTION 'CLOSED business entry denied' USING ERRCODE='55000';
END $cap$;

INSERT INTO raa_closed_control.business_guard_releases VALUES('wp4-rehearsal-006-business-closed',
 current_setting('raa.deployment_id')::uuid,current_setting('raa.checkpoint_id')::uuid,
 current_setting('raa.predecessor_id')::uuid,current_setting('raa.predecessor_digest'),
 current_setting('raa.source_digest'),current_setting('raa.bundle_digest'),current_setting('raa.baseline_digest'),
 20,current_database(),current_setting('raa.rehearsal_system'),pg_postmaster_start_time(),clock_timestamp(),false);
