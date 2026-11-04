-- Synthetic rollback-only contract checks; no report arithmetic/approval proof.
BEGIN;
DO $test$
DECLARE
    cid uuid;
    pending_cid uuid;
    metadata jsonb;
    first_proposal jsonb;
    replay jsonb;
    canonical text;
    report_body text := '{"schema_version":"deterministic-comparison-report-v1","fixture":"Not a real report","exact":0.73293010234875627641}';
    report_hash text;
    saved retail.approval_proposals%ROWTYPE;
    candidate retail.approval_proposals%ROWTYPE;
    variant integer;
BEGIN
    IF EXISTS (SELECT 1 FROM retail.approval_policies) OR EXISTS (SELECT 1 FROM retail.approval_proposals) THEN
        RAISE EXCEPTION 'Run only before real reviewer/proposal configuration';
    END IF;
    SET LOCAL ROLE raa_wp2_case_api;
    BEGIN
        PERFORM retail.api_prepare_approval_proposal_v1('00000000-0000-0000-0000-000000000000', 1, repeat('0',64));
        RAISE EXCEPTION 'Unconfigured reviewer was accepted';
    EXCEPTION WHEN object_not_in_prerequisite_state THEN NULL; END;
    metadata := retail.api_reserve_report_v1('rollback-wp4-proposal-015',
        'BCBE73B35F5B7BABF197FB0CB983A11F5D9FF929078D4AA53D171B1F2DF2E980',
        '2011-01-28 09:00', '2011-01-28 10:00', '2011-01-28 10:00')::jsonb;
    cid := (metadata ->> 'case_id')::uuid;
    metadata := retail.api_reserve_report_v1('rollback-wp4-pending-015',
        'BCBE73B35F5B7BABF197FB0CB983A11F5D9FF929078D4AA53D171B1F2DF2E980',
        '2011-01-28 09:00', '2011-01-28 10:00', '2011-01-28 10:00')::jsonb;
    pending_cid := (metadata ->> 'case_id')::uuid;
    IF retail.api_get_approval_proposal_v1(cid) IS NOT NULL THEN
        RAISE EXCEPTION 'Missing proposal became visible';
    END IF;
    RESET ROLE;
    -- This test identity exists only in the uncommitted transaction; not a human.
    INSERT INTO retail.approval_policies VALUES ('local-publication-v1', '00000000-0000-0000-0000-000000000015', 86400);
    report_hash := encode(sha256(convert_to(report_body, 'UTF8')), 'hex');
    INSERT INTO retail.report_revisions VALUES (cid, 1, 'deterministic-comparison-report-v1', report_body, report_hash, clock_timestamp());
    UPDATE retail.report_cases SET state='awaiting_approval', current_revision=1, updated_at=clock_timestamp() WHERE case_id=cid;
    INSERT INTO retail.report_audit_events(case_id,event_type,revision) VALUES (cid,'revision_created',1);
    SET LOCAL ROLE raa_wp2_case_api;
    BEGIN
        PERFORM retail.api_prepare_approval_proposal_v1(cid, 2, report_hash);
        RAISE EXCEPTION 'Unsupported revision was accepted';
    EXCEPTION WHEN invalid_parameter_value THEN NULL; END;
    BEGIN
        PERFORM retail.api_prepare_approval_proposal_v1(cid, 1, repeat('0',64));
        RAISE EXCEPTION 'Wrong report hash was accepted';
    EXCEPTION WHEN raise_exception THEN
        IF SQLERRM='Wrong report hash was accepted' THEN RAISE; END IF;
    END;
    BEGIN
        PERFORM retail.api_prepare_approval_proposal_v1(pending_cid, 1, report_hash);
        RAISE EXCEPTION 'Received case became a proposal';
    EXCEPTION WHEN raise_exception THEN
        IF SQLERRM='Received case became a proposal' THEN RAISE; END IF;
    END;
    first_proposal := retail.api_prepare_approval_proposal_v1(cid, 1, report_hash)::jsonb;
    FOR variant IN 1..10 LOOP
        replay := retail.api_prepare_approval_proposal_v1(cid, 1, report_hash)::jsonb;
        IF replay IS DISTINCT FROM first_proposal THEN RAISE EXCEPTION 'Replay changed immutable proposal'; END IF;
    END LOOP;
    canonical := first_proposal ->> 'canonical_payload_text';
    IF first_proposal ->> 'proposal_sha256' <> encode(sha256(convert_to(canonical,'UTF8')),'hex')
       OR first_proposal -> 'proposal' IS DISTINCT FROM canonical::jsonb
       OR first_proposal ->> 'review_status' <> 'pending_review'
       OR (first_proposal ->> 'decision_enabled')::boolean
       OR (first_proposal ->> 'approved')::boolean OR (first_proposal ->> 'published')::boolean
       OR first_proposal #>> '{proposal,report_payload_sha256}' <> report_hash
       OR first_proposal #>> '{proposal,action,content_sha256}' <> report_hash
       OR (first_proposal #>> '{proposal,action,content_bytes}')::integer <> octet_length(convert_to(report_body,'UTF8'))
       OR first_proposal #>> '{proposal,reviewer_id}' <> '00000000-0000-0000-0000-000000000015'
       OR first_proposal #>> '{proposal,action,target,relative_path}' <> 'reports/approved/v1/' || cid || '/revision-1.json'
       OR first_proposal #>> '{proposal,action,type}' <> 'publish_local_report_json_v1' THEN
        RAISE EXCEPTION 'Canonical proposal binding or disabled state failed';
    END IF;
    IF retail.api_get_approval_proposal_v1(cid)::jsonb IS DISTINCT FROM first_proposal
       OR retail.api_prepare_approval_proposal_v1('00000000-0000-0000-0000-000000000000',1,report_hash) IS NOT NULL THEN
        RAISE EXCEPTION 'Read/missing case contract failed';
    END IF;
    BEGIN
        PERFORM count(*) FROM retail.approval_proposals;
        RAISE EXCEPTION 'Direct proposal read allowed';
    EXCEPTION WHEN insufficient_privilege THEN NULL; END;
    BEGIN
        INSERT INTO retail.approval_policies VALUES ('local-publication-v1','00000000-0000-0000-0000-000000000099',86400);
        RAISE EXCEPTION 'Caller reviewer configuration allowed';
    EXCEPTION WHEN insufficient_privilege THEN NULL; END;
    BEGIN
        UPDATE retail.approval_proposals SET expires_at=clock_timestamp();
        RAISE EXCEPTION 'Caller proposal DML allowed';
    EXCEPTION WHEN insufficient_privilege THEN NULL; END;
    BEGIN
        PERFORM count(*) FROM retail.proposal_audit_events;
        RAISE EXCEPTION 'Direct proposal audit read allowed';
    EXCEPTION WHEN insufficient_privilege THEN NULL; END;
    RESET ROLE;
    SELECT * INTO STRICT saved FROM retail.approval_proposals WHERE case_id=cid;
    IF saved.expires_at - saved.created_at <> interval '24 hours'
       OR (first_proposal #>> '{proposal,expires_at}')::timestamptz
            - (first_proposal #>> '{proposal,created_at}')::timestamptz <> interval '24 hours'
       OR (first_proposal #>> '{proposal,created_at}')::timestamptz <> saved.created_at THEN
        RAISE EXCEPTION 'TTL does not start at proposal creation or differs from 86400 seconds';
    END IF;
    IF (SELECT count(*) FROM retail.approval_proposals WHERE case_id=cid) <> 1
       OR (SELECT count(*) FROM retail.proposal_audit_events WHERE proposal_id=saved.proposal_id) <> 1
       OR (SELECT state FROM retail.report_cases WHERE case_id=cid) <> 'awaiting_approval'
       OR (SELECT count(*) FROM retail.report_audit_events WHERE case_id=cid) <> 2 THEN
        RAISE EXCEPTION 'Proposal/audit single-effect or unchanged case failed';
    END IF;
    FOR variant IN 1..10 LOOP
        candidate := saved;
        candidate.proposal_id := gen_random_uuid();
        CASE variant
            WHEN 1 THEN candidate.report_payload_sha256 := repeat('0',64);
            WHEN 2 THEN candidate.reviewer_id := '00000000-0000-0000-0000-000000000099';
            WHEN 3 THEN candidate.payload_text := replace(candidate.payload_text,'reports/approved/v1/','https://untrusted.invalid/');
            WHEN 4 THEN candidate.report_revision := 2;
            WHEN 5 THEN candidate.expires_at := candidate.expires_at + interval '1 second';
            WHEN 6 THEN candidate.content_bytes := candidate.content_bytes + 1;
            WHEN 7 THEN candidate.created_at := clock_timestamp() + interval '1 day';
            WHEN 8 THEN candidate.payload_text := candidate.payload_text || ' ';
            WHEN 9 THEN candidate.payload_sha256 := NULL;
            WHEN 10 THEN candidate.payload_sha256 := repeat('0',64);
        END CASE;
        -- Rebuild to isolate changed column guards, unless testing payload text.
        IF variant NOT IN (3,8) THEN
            candidate.payload_text := retail.approval_proposal_payload_v1(candidate.proposal_id,candidate.case_id,
                candidate.report_revision,candidate.report_payload_sha256,candidate.content_bytes,candidate.reviewer_id,
                candidate.created_at,candidate.expires_at);
        END IF;
        IF variant NOT IN (9,10) THEN
            candidate.payload_sha256 := encode(sha256(convert_to(candidate.payload_text,'UTF8')),'hex');
        END IF;
        BEGIN
            INSERT INTO retail.approval_proposals SELECT candidate.*;
            RAISE EXCEPTION 'Modified binding was accepted: %',variant;
        EXCEPTION WHEN raise_exception THEN
            IF SQLERRM LIKE 'Modified binding was accepted:%' THEN RAISE; END IF;
        WHEN check_violation OR not_null_violation THEN NULL;
        END;
    END LOOP;
    BEGIN
        UPDATE retail.approval_proposals SET expires_at=expires_at+interval '1 second' WHERE case_id=cid;
        RAISE EXCEPTION 'Proposal edit allowed';
    EXCEPTION WHEN raise_exception THEN IF SQLERRM='Proposal edit allowed' THEN RAISE; END IF; END;
    BEGIN
        DELETE FROM retail.approval_proposals WHERE case_id=cid;
        RAISE EXCEPTION 'Proposal delete allowed';
    EXCEPTION WHEN raise_exception THEN IF SQLERRM='Proposal delete allowed' THEN RAISE; END IF; END;
    BEGIN
        TRUNCATE retail.proposal_audit_events;
        RAISE EXCEPTION 'Proposal audit truncate allowed';
    EXCEPTION WHEN raise_exception THEN IF SQLERRM='Proposal audit truncate allowed' THEN RAISE; END IF; END;
    BEGIN
        UPDATE retail.approval_policies SET ttl_seconds=60;
        RAISE EXCEPTION 'Policy edit allowed';
    EXCEPTION WHEN raise_exception THEN IF SQLERRM='Policy edit allowed' THEN RAISE; END IF; END;
    -- Separate past-created proposal tests derived expiry without editing history.
    INSERT INTO retail.report_revisions VALUES (pending_cid,1,'deterministic-comparison-report-v1',report_body,report_hash,clock_timestamp());
    UPDATE retail.report_cases SET state='awaiting_approval',current_revision=1,updated_at=clock_timestamp() WHERE case_id=pending_cid;
    INSERT INTO retail.report_audit_events(case_id,event_type,revision) VALUES (pending_cid,'revision_created',1);
    candidate := saved;
    candidate.proposal_id := gen_random_uuid(); candidate.case_id := pending_cid;
    -- statement_timestamp is constant for this DO statement and for the getter:
    -- test EXACT equality at expiry, without sleeping or changing DB time.
    candidate.created_at := statement_timestamp() - interval '24 hours';
    candidate.expires_at := candidate.created_at + interval '24 hours';
    IF candidate.expires_at <> statement_timestamp() THEN RAISE EXCEPTION 'Expiry boundary fixture differs'; END IF;
    candidate.payload_text := retail.approval_proposal_payload_v1(candidate.proposal_id,candidate.case_id,1,
        report_hash,candidate.content_bytes,candidate.reviewer_id,candidate.created_at,candidate.expires_at);
    candidate.payload_sha256 := encode(sha256(convert_to(candidate.payload_text,'UTF8')),'hex');
    INSERT INTO retail.approval_proposals SELECT candidate.*;
    INSERT INTO retail.proposal_audit_events(proposal_id,occurred_at) VALUES (candidate.proposal_id,candidate.created_at);
    SET LOCAL ROLE raa_wp2_case_api;
    replay := retail.api_prepare_approval_proposal_v1(pending_cid,1,report_hash)::jsonb;
    IF replay ->> 'review_status' <> 'expired'
       OR replay ->> 'canonical_payload_text' IS DISTINCT FROM candidate.payload_text
       OR (replay ->> 'approved')::boolean OR (replay ->> 'published')::boolean THEN
        RAISE EXCEPTION 'Expiry replay renewed or authorized proposal';
    END IF;
    RESET ROLE;
    RAISE NOTICE 'PASS|24h-from-proposal-creation|exact-expiry-boundary|ten-replays-no-extension|proposal-hash-target-reviewer|tamper-null-immutability|expired-not-renewed|no-decisions';
END
$test$;
ROLLBACK;
