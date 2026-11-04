-- Deployment artifact only. Set raa.f2_database to the verified isolated demo
-- approval database before applying. Never run against a historical database.
BEGIN;
DO $$ BEGIN
  IF current_database() !~ '^raa_wp4_dispatch_test_[a-f0-9]{12}$'
     OR current_database() IS DISTINCT FROM current_setting('raa.f2_database', true) THEN
    RAISE EXCEPTION 'Explicit isolated demo database binding required';
  END IF;
END $$;
-- Abort on existing objects/role: no silent adoption of unknown privileges.
CREATE ROLE raa_f2_creation NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
  NOINHERIT NOREPLICATION NOBYPASSRLS;
CREATE SCHEMA f2_creation;
REVOKE ALL ON SCHEMA f2_creation FROM PUBLIC;
CREATE TABLE f2_creation.operations (
  operation_id text PRIMARY KEY CHECK (operation_id ~ '^[a-f0-9-]{36}$'),
  operator_id text NOT NULL CHECK (operator_id ~ '^[a-f0-9-]{36}$'),
  nonce text NOT NULL UNIQUE CHECK (nonce ~ '^[a-f0-9]{64}$'),
  state text NOT NULL CHECK (state IN ('DISPATCHING','ADMITTED','UNCERTAIN','CREATED')),
  execution_id text UNIQUE CHECK (execution_id ~ '^[1-9][0-9]{0,18}$'),
  result text,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  CHECK ((state='CREATED') = (result IS NOT NULL)),
  CHECK (state NOT IN ('ADMITTED','CREATED') OR execution_id IS NOT NULL)
);
-- One unresolved dispatch per authenticated owner, including after a crash.
CREATE UNIQUE INDEX f2_one_unresolved_operator ON f2_creation.operations(operator_id)
  WHERE state IN ('DISPATCHING','ADMITTED','UNCERTAIN');
REVOKE ALL ON f2_creation.operations FROM PUBLIC;
GRANT USAGE ON SCHEMA f2_creation TO raa_f2_creation;
GRANT SELECT,INSERT,UPDATE ON f2_creation.operations TO raa_f2_creation;
-- No approval/publication grants. Configure LOGIN/password separately using
-- protected local configuration; no password belongs in this migration.
ALTER ROLE raa_f2_creation SET statement_timeout='5s';
ALTER ROLE raa_f2_creation SET lock_timeout='1s';
-- Fail closed if PUBLIC/inherited grants could give this role existing business
-- access. Do not change historical grants to make this migration pass.
DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
             WHERE n.nspname='retail' AND has_function_privilege('raa_f2_creation',p.oid,'EXECUTE'))
     OR EXISTS (SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
                WHERE n.nspname='retail' AND c.relkind IN ('r','p','v','m','f')
                  AND has_table_privilege('raa_f2_creation',c.oid,'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')) THEN
    RAISE EXCEPTION 'Creation role has unintended existing business privileges';
  END IF;
END $$;
COMMIT;
