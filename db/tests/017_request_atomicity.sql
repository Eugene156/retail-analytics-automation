\set ON_ERROR_STOP on
BEGIN;
CREATE FUNCTION pg_temp.fail_request_event_v2() RETURNS trigger LANGUAGE plpgsql AS $function$
BEGIN RAISE EXCEPTION 'Injected request-event failure'; END $function$;
CREATE TRIGGER wp4_v2_atomicity BEFORE INSERT ON retail.approval_request_events_v2
    FOR EACH ROW EXECUTE FUNCTION pg_temp.fail_request_event_v2();
DO $test$
DECLARE cid uuid:='61b10574-c842-4dae-8e8b-647f0d51ba55'; metadata text; report text;
BEGIN
    IF EXISTS(SELECT 1 FROM retail.approval_requests_v2 WHERE case_id=cid) THEN RAISE EXCEPTION 'Pre-issuance case required'; END IF;
    metadata:=retail.api_get_case_v1(cid); report:=retail.api_get_revision_v1(cid,1);
    EXECUTE 'SET LOCAL ROLE raa_wp2_case_api';
    BEGIN
        PERFORM retail.api_issue_approval_request_v2(cid,1,encode(sha256(convert_to(report,'UTF8')),'hex'),'wp4-atomicity-fixture-v2',NULL);
        RAISE EXCEPTION 'Audit fault did not fire';
    EXCEPTION WHEN raise_exception THEN
        IF SQLERRM<>'Injected request-event failure' THEN RAISE; END IF;
    END;
    EXECUTE 'RESET ROLE';
    IF EXISTS(SELECT 1 FROM retail.approval_requests_v2 WHERE case_id=cid)
       OR EXISTS(SELECT 1 FROM retail.approval_request_events_v2)
       OR metadata IS DISTINCT FROM retail.api_get_case_v1(cid)
       OR report IS DISTINCT FROM retail.api_get_revision_v1(cid,1) THEN RAISE EXCEPTION 'Partial request/event or changed report'; END IF;
    RAISE NOTICE 'PASS|actual-SQL-event-fault|request-and-event-rollback|unchanged-case-report';
END $test$;
ROLLBACK;
