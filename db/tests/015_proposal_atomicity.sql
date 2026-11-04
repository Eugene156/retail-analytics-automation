-- Transaction-only audit fault. All test configuration/triggers/rows roll back.
BEGIN;
SET LOCAL lock_timeout = '5s';
CREATE FUNCTION pg_temp.wp4_fail_proposal_audit() RETURNS trigger LANGUAGE plpgsql AS $function$
BEGIN
    RAISE EXCEPTION 'Synthetic proposal audit failure';
END
$function$;
CREATE TRIGGER wp4_atomicity_fixture BEFORE INSERT ON retail.proposal_audit_events
    FOR EACH ROW EXECUTE FUNCTION pg_temp.wp4_fail_proposal_audit();
DO $test$
DECLARE
    cid uuid;
    body text := '{"schema_version":"deterministic-comparison-report-v1","fixture":"Atomicity only"}';
    digest text;
BEGIN
    IF EXISTS (SELECT 1 FROM retail.approval_policies) OR EXISTS (SELECT 1 FROM retail.approval_proposals) THEN
        RAISE EXCEPTION 'Run only before real reviewer/proposal configuration';
    END IF;
    INSERT INTO retail.approval_policies VALUES ('local-publication-v1','00000000-0000-0000-0000-000000000015',86400);
    SET LOCAL ROLE raa_wp2_case_api;
    cid := (retail.api_reserve_report_v1('rollback-wp4-atomicity-015',
        'BCBE73B35F5B7BABF197FB0CB983A11F5D9FF929078D4AA53D171B1F2DF2E980',
        '2011-01-28 09:00','2011-01-28 10:00','2011-01-28 10:00')::jsonb ->> 'case_id')::uuid;
    RESET ROLE;
    digest := encode(sha256(convert_to(body,'UTF8')),'hex');
    INSERT INTO retail.report_revisions VALUES (cid,1,'deterministic-comparison-report-v1',body,digest,clock_timestamp());
    UPDATE retail.report_cases SET state='awaiting_approval',current_revision=1,updated_at=clock_timestamp() WHERE case_id=cid;
    INSERT INTO retail.report_audit_events(case_id,event_type,revision) VALUES (cid,'revision_created',1);
    SET LOCAL ROLE raa_wp2_case_api;
    BEGIN
        PERFORM retail.api_prepare_approval_proposal_v1(cid,1,digest);
        RAISE EXCEPTION 'Audit fault did not reject proposal';
    EXCEPTION WHEN raise_exception THEN
        IF SQLERRM <> 'Synthetic proposal audit failure' THEN RAISE; END IF;
    END;
    IF retail.api_get_approval_proposal_v1(cid) IS NOT NULL THEN RAISE EXCEPTION 'Partial proposal became visible'; END IF;
    RESET ROLE;
    IF EXISTS (SELECT 1 FROM retail.approval_proposals WHERE case_id=cid)
       OR EXISTS (SELECT 1 FROM retail.proposal_audit_events)
       OR (SELECT state FROM retail.report_cases WHERE case_id=cid) <> 'awaiting_approval'
       OR (SELECT count(*) FROM retail.report_revisions WHERE case_id=cid) <> 1 THEN
        RAISE EXCEPTION 'Audit fault left a partial proposal or changed its report';
    END IF;
    RAISE NOTICE 'PASS|actual-SQL-audit-fault|proposal-and-event-rollback|report-preserved';
END
$test$;
ROLLBACK;
