-- Clone-only additive compatibility. Not a live migration or a dispatch grant.
-- Caller wraps this complete file in one transaction, with fixed private bindings.
DO $guard$
DECLARE suffix text := substring(current_database() from '^raa_wp4_populated_rehearsal_([a-f0-9]{12})$');
BEGIN
 IF suffix IS NULL OR current_user IS DISTINCT FROM ('rehearsal_admin_'||suffix)
  OR session_user IS DISTINCT FROM current_user
  OR (SELECT system_identifier::text FROM pg_control_system())
     IS DISTINCT FROM current_setting('raa.rehearsal_system',true)
  OR coalesce(current_setting('raa.rehearsal_system',true),'') !~ '^[0-9]{10,20}$'
  OR coalesce(current_setting('raa.checkpoint_id',true),'') !~ '^[a-f0-9]{8}(-[a-f0-9]{4}){3}-[a-f0-9]{12}$'
  OR coalesce(current_setting('raa.deployment_id',true),'') !~ '^[a-f0-9]{8}(-[a-f0-9]{4}){3}-[a-f0-9]{12}$'
  OR coalesce(current_setting('raa.source_digest',true),'') !~ '^[a-f0-9]{64}$'
  OR coalesce(current_setting('raa.bundle_digest',true),'') !~ '^[a-f0-9]{64}$'
  OR coalesce(current_setting('raa.baseline_digest',true),'') !~ '^[a-f0-9]{64}$'
  OR pg_is_in_recovery() THEN
  RAISE EXCEPTION 'Bound fresh populated rehearsal required';
 END IF;
 IF NOT pg_try_advisory_xact_lock(hashtextextended('wp4-populated-deployment001',0)) THEN
  RAISE EXCEPTION 'Deployment is busy' USING ERRCODE='55P03';
 END IF;
 IF (SELECT array_agg(version ORDER BY version) FROM retail.schema_migrations)
     IS DISTINCT FROM ARRAY(SELECT generate_series(1,20))
  OR to_regnamespace('raa_deployment') IS NOT NULL
  OR to_regclass('retail.publication_dispatch_events_v1') IS NOT NULL
  OR to_regclass('retail.portal_approval_requests_v3') IS NOT NULL
  OR to_regclass('retail.portal_worker_events_v1') IS NOT NULL
  OR EXISTS(SELECT FROM retail.review_decisions_v1)
  OR EXISTS(SELECT FROM retail.publication_outbox_v1)
  OR (SELECT payload_sha256 FROM retail.report_revisions
      WHERE case_id='61b10574-c842-4dae-8e8b-647f0d51ba55' AND revision=1)
     IS DISTINCT FROM '2e913def90e1a5e41f9ac6009dd49b7411a8e703d936cdc6b7e5f7a95ed12b07'
  OR EXISTS(SELECT FROM pg_roles WHERE (rolname='g0_user' OR rolname LIKE 'raa\_%' ESCAPE '\')
      AND (rolcanlogin OR rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication OR rolbypassrls))
  OR EXISTS(SELECT FROM pg_auth_members m JOIN pg_roles a ON a.oid=m.roleid
      JOIN pg_roles b ON b.oid=m.member WHERE a.rolname='g0_user' OR b.rolname='g0_user'
      OR a.rolname LIKE 'raa\_%' ESCAPE '\' OR b.rolname LIKE 'raa\_%' ESCAPE '\'
      OR a.rolname=current_user OR b.rolname=current_user) THEN
  RAISE EXCEPTION 'Unchanged disabled main020 clone required';
 END IF;
END $guard$;

CREATE SCHEMA raa_deployment;
REVOKE ALL ON SCHEMA raa_deployment FROM PUBLIC;
CREATE TABLE raa_deployment.releases (
 bundle_id text PRIMARY KEY CHECK(bundle_id='wp4-rehearsal-001'),
 deployment_id uuid NOT NULL UNIQUE,
 checkpoint_id uuid NOT NULL,
 source_digest text NOT NULL CHECK(source_digest ~ '^[a-f0-9]{64}$'),
 bundle_digest text NOT NULL CHECK(bundle_digest ~ '^[a-f0-9]{64}$'),
 baseline_digest text NOT NULL CHECK(baseline_digest ~ '^[a-f0-9]{64}$'),
 predecessor_id text CHECK(predecessor_id IS NULL),
 base_version integer NOT NULL CHECK(base_version=20),
 target_database name NOT NULL CHECK(target_database::text ~ '^raa_wp4_populated_rehearsal_[a-f0-9]{12}$'),
 target_system text NOT NULL CHECK(target_system ~ '^[0-9]{10,20}$'),
 installed_at timestamptz NOT NULL CHECK(isfinite(installed_at)),
 admitted boolean NOT NULL DEFAULT false CHECK(admitted=false)
);
REVOKE ALL ON raa_deployment.releases FROM PUBLIC;
CREATE TRIGGER immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON raa_deployment.releases
 FOR EACH STATEMENT EXECUTE FUNCTION retail.reject_source_mutation();

-- Exact legacy021 table shape, with deliberately stricter non-admitted writes.
-- Required by025's legacy fence; no021 helper/API/function/grant is installed.
CREATE TABLE retail.publication_dispatch_events_v1 (
 event_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 action_id uuid NOT NULL REFERENCES retail.publication_outbox_v1(action_id),
 sequence integer NOT NULL CHECK(sequence>0),
 kind text NOT NULL CHECK(kind IN ('claimed','observed','cancelled')),
 mode text NOT NULL CHECK(mode IN ('write','reconcile')),
 state text NOT NULL CHECK(state IN ('in_progress','unknown','retryable','succeeded','cancelled','dead_letter')),
 write_attempts integer NOT NULL CHECK(write_attempts BETWEEN 0 AND 3),
 lease_id uuid,
 lease_expires_at timestamptz CHECK(isfinite(lease_expires_at)),
 claim_key text CHECK(claim_key COLLATE "C" ~ '^[A-Za-z0-9_-]{8,128}$'),
 result text CHECK(result IN ('matching','missing','unknown','ambiguous')),
 observed_sha256 text CHECK(observed_sha256 ~ '^[a-f0-9]{64}$'),
 observed_bytes integer CHECK(observed_bytes BETWEEN 1 AND 131072),
 occurred_at timestamptz NOT NULL CHECK(isfinite(occurred_at)),
 UNIQUE(action_id,sequence), UNIQUE(action_id,claim_key)
);
ALTER TABLE retail.publication_dispatch_events_v1 OWNER TO g0_user;
REVOKE ALL ON retail.publication_dispatch_events_v1 FROM PUBLIC;
CREATE TRIGGER deployment001_dispatch_denied BEFORE INSERT OR UPDATE OR DELETE OR TRUNCATE
 ON retail.publication_dispatch_events_v1 FOR EACH STATEMENT EXECUTE FUNCTION retail.reject_source_mutation();

-- A receipt is visible only after the surrounding transaction commits.
INSERT INTO raa_deployment.releases(bundle_id,deployment_id,checkpoint_id,source_digest,bundle_digest,
 baseline_digest,predecessor_id,base_version,target_database,target_system,installed_at,admitted)
VALUES('wp4-rehearsal-001',current_setting('raa.deployment_id')::uuid,current_setting('raa.checkpoint_id')::uuid,
 current_setting('raa.source_digest'),current_setting('raa.bundle_digest'),current_setting('raa.baseline_digest'),
 NULL,20,current_database(),(SELECT system_identifier::text FROM pg_control_system()),clock_timestamp(),false);
