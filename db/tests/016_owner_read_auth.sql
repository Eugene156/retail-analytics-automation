-- Run before live bootstrap only. No real credential or policy is replaced.
\set ON_ERROR_STOP on
BEGIN;
DO $test$
BEGIN
    IF current_database() <> 'raa_wp2_validation'
       OR EXISTS(SELECT 1 FROM retail.owner_credentials)
       OR EXISTS(SELECT 1 FROM retail.approval_policies) THEN
        RAISE EXCEPTION 'Unconfigured validation database required';
    END IF;
END
$test$;
INSERT INTO retail.owner_credentials(reviewer_id, token_sha256)
    VALUES ('00000000-0000-0000-0000-000000000016', repeat('a',64));
INSERT INTO retail.approval_policies VALUES
    ('local-publication-v1','00000000-0000-0000-0000-000000000016',86400);
CREATE TEMP TABLE before_owner_auth AS SELECT
    retail.api_get_case_v1('61b10574-c842-4dae-8e8b-647f0d51ba55') AS metadata,
    retail.api_get_revision_v1('61b10574-c842-4dae-8e8b-647f0d51ba55',1) AS payload;

SET LOCAL ROLE raa_wp4_reviewer_api;
DO $test$
DECLARE value text; command text;
BEGIN
    IF retail.api_owner_identity_v1(repeat('a',64)) IS DISTINCT FROM
       '00000000-0000-0000-0000-000000000016'::uuid
       OR retail.api_owner_identity_v1(repeat('b',64)) IS NOT NULL
       OR retail.api_owner_identity_v1(NULL) IS NOT NULL THEN RAISE EXCEPTION 'Identity gate failed'; END IF;
    value := retail.api_owner_case_v1(repeat('a',64),'61b10574-c842-4dae-8e8b-647f0d51ba55');
    IF value IS NULL OR (value::jsonb ->> 'approved') <> 'false' THEN RAISE EXCEPTION 'Read failed'; END IF;
    IF retail.api_owner_revision_v1(repeat('a',64),'61b10574-c842-4dae-8e8b-647f0d51ba55',2) IS NOT NULL
       OR retail.api_owner_proposal_v1(repeat('a',64),'61b10574-c842-4dae-8e8b-647f0d51ba55') IS NOT NULL THEN
        RAISE EXCEPTION 'Unexpected object';
    END IF;
    BEGIN
        PERFORM retail.api_owner_case_v1(repeat('b',64),'61b10574-c842-4dae-8e8b-647f0d51ba55');
        RAISE EXCEPTION 'Wrong credential accepted';
    EXCEPTION WHEN insufficient_privilege THEN NULL; END;
    FOREACH command IN ARRAY ARRAY[
      'SELECT * FROM retail.owner_credentials', 'SELECT * FROM retail.report_revisions',
      'UPDATE retail.owner_credentials SET revoked_at=clock_timestamp()',
      'SELECT retail.api_get_case_v1(gen_random_uuid())',
      'SELECT retail.api_prepare_approval_proposal_v1(gen_random_uuid(),1,repeat(''a'',64))',
      'CREATE TABLE retail.unauthorized_owner_test(id integer)'] LOOP
        BEGIN EXECUTE command; RAISE EXCEPTION 'Unauthorized privilege';
        EXCEPTION WHEN insufficient_privilege THEN NULL; END;
    END LOOP;
END
$test$;
RESET ROLE;
SET LOCAL ROLE raa_wp2_case_api;
DO $test$ BEGIN
    BEGIN PERFORM retail.api_owner_identity_v1(repeat('a',64)); RAISE EXCEPTION 'Service gained owner access';
    EXCEPTION WHEN insufficient_privilege THEN NULL; END;
END $test$;
RESET ROLE;

UPDATE retail.owner_credentials SET revoked_at=clock_timestamp();
SET LOCAL ROLE raa_wp4_reviewer_api;
DO $test$ BEGIN
    IF retail.api_owner_identity_v1(repeat('a',64)) IS NOT NULL THEN RAISE EXCEPTION 'Revocation ignored'; END IF;
    BEGIN
      PERFORM retail.api_owner_revision_v1(repeat('a',64),'61b10574-c842-4dae-8e8b-647f0d51ba55',1);
      RAISE EXCEPTION 'Revoked read accepted';
    EXCEPTION WHEN insufficient_privilege THEN NULL; END;
END $test$;
RESET ROLE;
DO $test$
DECLARE command text;
BEGIN
    FOREACH command IN ARRAY ARRAY[
      'UPDATE retail.owner_credentials SET revoked_at=NULL',
      'UPDATE retail.owner_credentials SET token_sha256=repeat(''b'',64)',
      'DELETE FROM retail.owner_credentials', 'TRUNCATE retail.owner_credentials'] LOOP
        BEGIN EXECUTE command;
        EXCEPTION WHEN raise_exception THEN CONTINUE; END;
        RAISE EXCEPTION 'Credential history changed';
    END LOOP;
    IF (SELECT metadata FROM before_owner_auth) IS DISTINCT FROM
        retail.api_get_case_v1('61b10574-c842-4dae-8e8b-647f0d51ba55')
       OR (SELECT payload FROM before_owner_auth) IS DISTINCT FROM
        retail.api_get_revision_v1('61b10574-c842-4dae-8e8b-647f0d51ba55',1) THEN
        RAISE EXCEPTION 'Read-only checks mutated report';
    END IF;
END
$test$;
SELECT 'PASS|owner-read-auth|server-mapping|scoped-rights|revocation|history|unchanged-report';
ROLLBACK;
