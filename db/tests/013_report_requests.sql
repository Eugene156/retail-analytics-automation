-- Fast rollback-only lifecycle/idempotency/permission/immutability checks.
BEGIN;
DO $test$
DECLARE
    first_case jsonb;
    replay jsonb;
    cid uuid;
    body text := '{"schema_version":"deterministic-comparison-report-v1","exact":0.73293010234875627641}';
BEGIN
    SET LOCAL ROLE raa_wp2_case_api;
    first_case := retail.api_reserve_report_v1('rollback-test-013',
        'BCBE73B35F5B7BABF197FB0CB983A11F5D9FF929078D4AA53D171B1F2DF2E980',
        '2011-01-28 09:00', '2011-01-28 10:00', '2011-01-28 10:00')::jsonb;
    replay := retail.api_reserve_report_v1('rollback-test-013',
        'BCBE73B35F5B7BABF197FB0CB983A11F5D9FF929078D4AA53D171B1F2DF2E980',
        '2011-01-28 09:00', '2011-01-28 10:00', '2011-01-28 10:00')::jsonb;
    IF first_case IS DISTINCT FROM replay OR first_case ->> 'state' <> 'received'
       OR jsonb_array_length(first_case -> 'audit_events') <> 1 THEN
        RAISE EXCEPTION 'Reservation replay failed';
    END IF;
    cid := (first_case ->> 'case_id')::uuid;
    BEGIN
        PERFORM retail.api_reserve_report_v1('rollback-test-013',
            'BCBE73B35F5B7BABF197FB0CB983A11F5D9FF929078D4AA53D171B1F2DF2E980',
            '2011-01-28 08:00', '2011-01-28 10:00', '2011-01-28 10:00');
        RAISE EXCEPTION 'Changed request was accepted';
    EXCEPTION WHEN unique_violation THEN NULL; END;
    BEGIN
        PERFORM retail.api_reserve_report_v1('rollback-bad-013',
            'BCBE73B35F5B7BABF197FB0CB983A11F5D9FF929078D4AA53D171B1F2DF2E980',
            '2011-12-09 12:00', '2011-12-09 13:00', '2011-12-09 13:00');
        RAISE EXCEPTION 'Invalid source range was accepted';
    EXCEPTION WHEN invalid_parameter_value THEN NULL; END;
    BEGIN
        PERFORM count(*) FROM retail.source_rows;
        RAISE EXCEPTION 'Raw read was allowed';
    EXCEPTION WHEN insufficient_privilege THEN NULL; END;
    BEGIN
        UPDATE retail.report_cases SET state = 'awaiting_approval' WHERE case_id = cid;
        RAISE EXCEPTION 'Direct case DML was allowed';
    EXCEPTION WHEN insufficient_privilege THEN NULL; END;
    BEGIN
        PERFORM count(*) FROM retail.report_revisions;
        RAISE EXCEPTION 'Direct revision read was allowed';
    EXCEPTION WHEN insufficient_privilege THEN NULL; END;
    BEGIN
        PERFORM retail.api_comparison_report_v1('bad', now()::timestamp, now()::timestamp, now()::timestamp);
        RAISE EXCEPTION 'Unscoped wrapper was allowed';
    EXCEPTION WHEN insufficient_privilege THEN NULL; END;
    RESET ROLE;
    BEGIN
        UPDATE retail.report_cases SET request_identity = '{}' WHERE case_id = cid;
        RAISE EXCEPTION 'Identity change was allowed';
    EXCEPTION WHEN raise_exception THEN
        IF SQLERRM = 'Identity change was allowed' THEN RAISE; END IF;
    END;
    BEGIN
        INSERT INTO retail.report_revisions VALUES (cid, 1, 'deterministic-comparison-report-v1',
            '{}', encode(sha256(convert_to('{}', 'UTF8')), 'hex'), clock_timestamp());
        RAISE EXCEPTION 'Missing payload schema was accepted';
    EXCEPTION WHEN check_violation THEN NULL; END;
    BEGIN
        INSERT INTO retail.report_revisions VALUES (cid, 1, 'deterministic-comparison-report-v1',
            body, repeat('0', 64), clock_timestamp());
        RAISE EXCEPTION 'Wrong payload hash was accepted';
    EXCEPTION WHEN check_violation THEN NULL; END;
    -- Synthetic persistence fixture is not evidence of report arithmetic.
    INSERT INTO retail.report_revisions VALUES (cid, 1, 'deterministic-comparison-report-v1',
        body, encode(sha256(convert_to(body, 'UTF8')), 'hex'), clock_timestamp());
    UPDATE retail.report_cases SET state = 'awaiting_approval', current_revision = 1,
        updated_at = clock_timestamp() WHERE case_id = cid;
    INSERT INTO retail.report_audit_events(case_id, event_type, revision) VALUES (cid, 'revision_created', 1);
    BEGIN
        UPDATE retail.report_revisions SET payload_text = '{}' WHERE case_id = cid;
        RAISE EXCEPTION 'Revision edit was allowed';
    EXCEPTION WHEN raise_exception THEN
        IF SQLERRM = 'Revision edit was allowed' THEN RAISE; END IF;
    END;
    BEGIN
        DELETE FROM retail.report_audit_events WHERE case_id = cid;
        RAISE EXCEPTION 'Audit delete was allowed';
    EXCEPTION WHEN raise_exception THEN
        IF SQLERRM = 'Audit delete was allowed' THEN RAISE; END IF;
    END;
    BEGIN
        TRUNCATE retail.report_audit_events;
        RAISE EXCEPTION 'Audit truncate was allowed';
    EXCEPTION WHEN raise_exception THEN
        IF SQLERRM = 'Audit truncate was allowed' THEN RAISE; END IF;
    END;
    BEGIN
        DELETE FROM retail.report_cases WHERE case_id = cid;
        RAISE EXCEPTION 'Case delete was allowed';
    EXCEPTION WHEN raise_exception THEN
        IF SQLERRM = 'Case delete was allowed' THEN RAISE; END IF;
    END;
    SET LOCAL ROLE raa_wp2_case_api;
    replay := retail.api_finish_report_v1(cid)::jsonb;
    IF replay ->> 'state' <> 'awaiting_approval' OR replay ->> 'revision' <> '1'
       OR (replay ->> 'approved')::boolean OR (replay ->> 'published')::boolean
       OR jsonb_array_length(replay -> 'audit_events') <> 2
       OR retail.api_get_revision_v1(cid, 1) IS DISTINCT FROM body
       OR retail.api_get_case_v1('00000000-0000-0000-0000-000000000000') IS NOT NULL THEN
        RAISE EXCEPTION 'Stored revision or metadata replay failed';
    END IF;
    RESET ROLE;
    RAISE NOTICE 'PASS|request-replay|conflict|range|scoped-role|immutable-case-revision-audit|draft-only';
END
$test$;
ROLLBACK;
