-- Clone-only ACL hardening. No LOGIN, session rebinding or runtime admission.
DO $guard$
DECLARE suffix text:=substring(current_database() from '^raa_wp4_populated_rehearsal_([a-f0-9]{12})$');
 expected regprocedure[]:=ARRAY[
 'retail.assert_sale_invoice_consistency_v1(text,text,timestamp,timestamp)',
 'retail.assert_uci_502_overlap_v1(text)','retail.assert_uci_502_sheet_domain_v1(text)',
 'retail.canonical_period_kpis_asof_v1(text,timestamp,timestamp,timestamp)',
 'retail.canonical_period_kpis_v1(text,timestamp,timestamp)',
 'retail.canonical_period_line_keys_v1(text,timestamp,timestamp)',
 'retail.cell_value(jsonb,integer)','retail.classify_snapshot_v1(text)',
 'retail.deterministic_comparison_report_v1(text,timestamp,timestamp,timestamp)',
 'retail.deterministic_period_report_v1(text,timestamp,timestamp,timestamp)',
 'retail.guard_approval_proposal_insert_v1()','retail.guard_report_case_mutation()',
 'retail.period_kpis_v1(text,text,timestamp,timestamp)',
 'retail.reject_source_mutation()','retail.try_numeric(text)','retail.try_source_timestamp(text)']::regprocedure[];
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
  RAISE EXCEPTION 'Exact populated rehearsal context required'; END IF;
 IF NOT pg_try_advisory_xact_lock(hashtextextended('wp4-populated-deployment001',0)) THEN
  RAISE EXCEPTION 'Deployment is busy' USING ERRCODE='55P03'; END IF;
 IF to_regclass('raa_deployment.portal_schema_releases') IS NULL THEN
  RAISE EXCEPTION 'Committed deployment002 required'; END IF;
 IF NOT EXISTS(SELECT FROM raa_deployment.portal_schema_releases r JOIN raa_deployment.releases p
   ON p.deployment_id=r.predecessor_id AND p.bundle_digest=r.predecessor_digest
   WHERE r.bundle_id='wp4-rehearsal-002' AND p.bundle_id='wp4-rehearsal-001'
   AND r.deployment_id=current_setting('raa.predecessor_id')::uuid
   AND r.bundle_digest=current_setting('raa.predecessor_digest')
   AND r.checkpoint_id=current_setting('raa.checkpoint_id')::uuid
   AND r.source_digest=current_setting('raa.source_digest') AND r.baseline_digest=current_setting('raa.baseline_digest')
   AND r.target_system=current_setting('raa.rehearsal_system') AND r.target_database=current_database()
   AND p.target_database=r.target_database AND p.target_system=r.target_system
   AND p.checkpoint_id=r.checkpoint_id AND p.source_digest=r.source_digest AND p.baseline_digest=r.baseline_digest
   AND NOT r.admitted AND NOT p.admitted AND r.base_version=20 AND p.base_version=20)
  OR (SELECT count(*) FROM raa_deployment.portal_schema_releases)<>1 OR (SELECT count(*) FROM raa_deployment.releases)<>1
  OR to_regclass('raa_deployment.acl_hardening_releases') IS NOT NULL
  OR (SELECT array_agg(version ORDER BY version) FROM retail.schema_migrations) IS DISTINCT FROM ARRAY(SELECT generate_series(1,20))
  OR EXISTS(SELECT FROM retail.review_decisions_v1) OR EXISTS(SELECT FROM retail.publication_outbox_v1)
  OR EXISTS(SELECT FROM retail.publication_dispatch_events_v1)
  OR EXISTS(SELECT FROM retail.portal_approval_requests_v3) OR EXISTS(SELECT FROM retail.portal_worker_events_v1)
  OR EXISTS(SELECT FROM retail.portal_review_decisions_v2) OR EXISTS(SELECT FROM retail.portal_publications_v2)
  OR EXISTS(SELECT FROM retail.portal_publication_intents_v2) OR EXISTS(SELECT FROM retail.portal_publication_audit_v2)
  OR EXISTS(SELECT FROM retail.portal_legacy_transitions_v1) OR EXISTS(SELECT FROM retail.portal_legacy_transition_events_v1)
  OR EXISTS(SELECT FROM pg_roles WHERE (rolname='g0_user' OR rolname LIKE 'raa\_%' ESCAPE '\')
     AND (rolcanlogin OR rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication OR rolbypassrls))
  OR EXISTS(SELECT FROM pg_auth_members m JOIN pg_roles a ON a.oid=m.roleid JOIN pg_roles b ON b.oid=m.member
     WHERE a.rolname='g0_user' OR b.rolname='g0_user' OR a.rolname LIKE 'raa\_%' ESCAPE '\'
     OR b.rolname LIKE 'raa\_%' ESCAPE '\' OR a.rolname=current_user OR b.rolname=current_user) THEN
  RAISE EXCEPTION 'Exact non-admitted populated002 predecessor required'; END IF;
 IF (SELECT array_agg(p.oid ORDER BY p.oid) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
   WHERE n.nspname='retail' AND EXISTS(SELECT FROM aclexplode(coalesce(p.proacl,acldefault('f',p.proowner))) a
     WHERE a.grantee=0 AND a.privilege_type='EXECUTE'))
   IS DISTINCT FROM (SELECT array_agg(x::oid ORDER BY x::oid) FROM unnest(expected) x) THEN
  RAISE EXCEPTION 'Exact sixteen historical PUBLIC functions required'; END IF;
 IF EXISTS(SELECT FROM pg_proc WHERE oid=ANY(expected::oid[]) AND pg_get_userbyid(proowner)<>'g0_user') THEN
  RAISE EXCEPTION 'Original disabled function owner required'; END IF;
END $guard$;

SET LOCAL ROLE g0_user;
REVOKE EXECUTE ON FUNCTION
 retail.assert_sale_invoice_consistency_v1(text,text,timestamp,timestamp),
 retail.assert_uci_502_overlap_v1(text),retail.assert_uci_502_sheet_domain_v1(text),
 retail.canonical_period_kpis_asof_v1(text,timestamp,timestamp,timestamp),
 retail.canonical_period_kpis_v1(text,timestamp,timestamp),retail.canonical_period_line_keys_v1(text,timestamp,timestamp),
 retail.cell_value(jsonb,integer),retail.classify_snapshot_v1(text),
 retail.deterministic_comparison_report_v1(text,timestamp,timestamp,timestamp),
 retail.deterministic_period_report_v1(text,timestamp,timestamp,timestamp),
 retail.guard_approval_proposal_insert_v1(),retail.guard_report_case_mutation(),
 retail.period_kpis_v1(text,text,timestamp,timestamp),retail.reject_source_mutation(),
 retail.try_numeric(text),retail.try_source_timestamp(text) FROM PUBLIC;
RESET ROLE;

CREATE TABLE raa_deployment.acl_hardening_releases (
 bundle_id text PRIMARY KEY CHECK(bundle_id='wp4-rehearsal-003'),
 deployment_id uuid NOT NULL UNIQUE, checkpoint_id uuid NOT NULL,
 predecessor_id uuid NOT NULL REFERENCES raa_deployment.portal_schema_releases(deployment_id),
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
REVOKE ALL ON raa_deployment.acl_hardening_releases FROM PUBLIC;
CREATE TRIGGER immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON raa_deployment.acl_hardening_releases
 FOR EACH STATEMENT EXECUTE FUNCTION retail.reject_source_mutation();
INSERT INTO raa_deployment.acl_hardening_releases
 SELECT 'wp4-rehearsal-003',current_setting('raa.deployment_id')::uuid,current_setting('raa.checkpoint_id')::uuid,
 current_setting('raa.predecessor_id')::uuid,current_setting('raa.predecessor_digest'),current_setting('raa.source_digest'),
 current_setting('raa.bundle_digest'),current_setting('raa.baseline_digest'),20,current_database(),
 (SELECT system_identifier::text FROM pg_control_system()),clock_timestamp(),false;
