-- Actual PostgreSQL functions, fully rolled back. No human sign-in/decision.
BEGIN;
SET LOCAL timezone='UTC';
DO $test$
DECLARE owner_digest text; identity uuid; session text:=repeat('a',64); csrf text:=repeat('b',64);
 old text:=repeat('c',64); report_before text; requests_before bigint; events_before bigint; n integer;
BEGIN
 SELECT token_sha256,reviewer_id INTO STRICT owner_digest,identity FROM retail.owner_credentials WHERE revoked_at IS NULL;
 report_before:=retail.api_get_revision_v1('61b10574-c842-4dae-8e8b-647f0d51ba55',1);
 SELECT count(*) INTO requests_before FROM retail.approval_requests_v2;
 SELECT count(*) INTO events_before FROM retail.approval_request_events_v2;
 IF retail.api_portal_identity_v1(session) IS NOT NULL THEN RAISE EXCEPTION 'Unknown session accepted'; END IF;
 BEGIN
   PERFORM retail.api_portal_login_v1(repeat('0',64),session,csrf,NULL);
   RAISE EXCEPTION 'Wrong owner accepted';
 EXCEPTION WHEN insufficient_privilege THEN NULL; END;
 IF retail.api_portal_login_v1(owner_digest,old,csrf,NULL) IS DISTINCT FROM identity THEN RAISE EXCEPTION 'Login failed'; END IF;
 IF retail.api_portal_login_v1(owner_digest,session,csrf,old) IS DISTINCT FROM identity THEN RAISE EXCEPTION 'Second login failed'; END IF;
 IF retail.api_portal_identity_v1(old) IS NOT NULL
    OR retail.api_portal_identity_v1(session) IS DISTINCT FROM identity THEN RAISE EXCEPTION 'Rotation failed'; END IF;
 IF NOT EXISTS(SELECT 1 FROM retail.owner_portal_sessions WHERE session_sha256=session AND expires_at-created_at=interval '1 hour')
   THEN RAISE EXCEPTION 'Wrong absolute TTL'; END IF;
 BEGIN
   PERFORM retail.api_portal_logout_v1(session,repeat('0',64));
   RAISE EXCEPTION 'Wrong CSRF accepted';
 EXCEPTION WHEN insufficient_privilege THEN NULL; END;
 PERFORM retail.api_portal_requests_v1(session);
 PERFORM retail.api_portal_case_v1(session,'61b10574-c842-4dae-8e8b-647f0d51ba55');
 IF retail.api_portal_revision_v1(session,'61b10574-c842-4dae-8e8b-647f0d51ba55',1) IS DISTINCT FROM report_before
   THEN RAISE EXCEPTION 'Report changed'; END IF;
 IF NOT retail.api_portal_logout_v1(session,csrf) THEN RAISE EXCEPTION 'Logout result failed'; END IF;
 IF retail.api_portal_identity_v1(session) IS NOT NULL THEN
   RAISE EXCEPTION 'Logout failed'; END IF;
 BEGIN
   PERFORM retail.api_portal_logout_v1(session,csrf);
   RAISE EXCEPTION 'Logout replay accepted';
 EXCEPTION WHEN insufficient_privilege THEN NULL; END;
 BEGIN
   UPDATE retail.owner_portal_sessions SET revoked_at=NULL WHERE session_sha256=session;
   RAISE EXCEPTION 'Session reenabled';
 EXCEPTION WHEN raise_exception THEN IF SQLERRM='Session reenabled' THEN RAISE; END IF; END;
 BEGIN
   UPDATE retail.owner_portal_sessions SET expires_at=expires_at+interval '1 hour' WHERE session_sha256=old;
   RAISE EXCEPTION 'Sliding session accepted';
 EXCEPTION WHEN raise_exception THEN IF SQLERRM='Sliding session accepted' THEN RAISE; END IF; END;
 BEGIN
   DELETE FROM retail.owner_portal_sessions WHERE session_sha256=old;
   RAISE EXCEPTION 'History deleted';
 EXCEPTION WHEN raise_exception THEN IF SQLERRM='History deleted' THEN RAISE; END IF; END;
 INSERT INTO retail.owner_portal_sessions VALUES(repeat('d',64),identity,csrf,
   statement_timestamp()-interval '1 hour',statement_timestamp(),NULL);
 IF retail.api_portal_identity_v1(repeat('d',64)) IS NOT NULL THEN RAISE EXCEPTION 'Expiry equality accepted'; END IF;
 -- Cap is enforced transactionally; old expired/revoked rows do not count.
 FOR n IN 1..8 LOOP
   PERFORM retail.api_portal_login_v1(owner_digest,lpad(n::text,64,'0'),csrf,NULL);
 END LOOP;
 BEGIN
   PERFORM retail.api_portal_login_v1(owner_digest,repeat('e',64),csrf,NULL);
   RAISE EXCEPTION 'Session cap ignored';
 EXCEPTION WHEN program_limit_exceeded THEN NULL; END;
 UPDATE retail.owner_credentials SET revoked_at=clock_timestamp() WHERE reviewer_id=identity;
 IF retail.api_portal_identity_v1(lpad('1',64,'0')) IS NOT NULL THEN RAISE EXCEPTION 'Owner revocation ignored'; END IF;
 BEGIN
   PERFORM retail.api_portal_requests_v1(lpad('1',64,'0'));
   RAISE EXCEPTION 'Revoked read accepted';
 EXCEPTION WHEN insufficient_privilege THEN NULL; END;
 IF requests_before<>(SELECT count(*) FROM retail.approval_requests_v2)
    OR events_before<>(SELECT count(*) FROM retail.approval_request_events_v2)
    OR report_before IS DISTINCT FROM retail.api_get_revision_v1('61b10574-c842-4dae-8e8b-647f0d51ba55',1) THEN
   RAISE EXCEPTION 'Business state changed'; END IF;
END $test$;
ROLLBACK;

BEGIN;
CREATE FUNCTION retail.portal_test_fault() RETURNS trigger LANGUAGE plpgsql AS $fault$
 BEGIN RAISE EXCEPTION 'Injected auth audit failure'; END $fault$;
CREATE TRIGGER portal_test_fault BEFORE INSERT ON retail.owner_portal_events
 FOR EACH ROW EXECUTE FUNCTION retail.portal_test_fault();
DO $test$ DECLARE owner_digest text; BEGIN
 SELECT token_sha256 INTO STRICT owner_digest FROM retail.owner_credentials WHERE revoked_at IS NULL;
 BEGIN
   PERFORM retail.api_portal_login_v1(owner_digest,repeat('f',64),repeat('b',64),NULL);
   RAISE EXCEPTION 'Audit failure not raised';
 EXCEPTION WHEN raise_exception THEN
   IF SQLERRM<>'Injected auth audit failure' THEN RAISE; END IF;
 END;
 IF EXISTS(SELECT 1 FROM retail.owner_portal_sessions WHERE session_sha256=repeat('f',64)) THEN
   RAISE EXCEPTION 'Partial session committed'; END IF;
END $test$;
ROLLBACK;

BEGIN;
SET LOCAL ROLE raa_wp4_portal_api;
DO $test$ BEGIN
 IF has_table_privilege(current_user,'retail.owner_credentials','SELECT')
    OR has_table_privilege(current_user,'retail.owner_portal_sessions','SELECT,INSERT,UPDATE,DELETE,TRUNCATE')
    OR has_table_privilege(current_user,'retail.approval_requests_v2','SELECT,INSERT,UPDATE,DELETE,TRUNCATE')
    OR has_function_privilege(current_user,'retail.api_issue_approval_request_v2(uuid,integer,text,text,uuid)','EXECUTE')
    OR has_function_privilege(current_user,'retail.api_owner_identity_v1(text)','EXECUTE')
    OR has_schema_privilege(current_user,'retail','CREATE') THEN RAISE EXCEPTION 'Portal role too broad'; END IF;
 BEGIN
   PERFORM 1 FROM retail.owner_credentials;
   RAISE EXCEPTION 'Direct credential read accepted';
 EXCEPTION WHEN insufficient_privilege THEN NULL; END;
END $test$;
ROLLBACK;
SELECT 'PASS|portal-sql|login-rotation-csrf-logout|absolute-expiry-cap-revocation|immutability-atomicity-scoped-role|rollback';
