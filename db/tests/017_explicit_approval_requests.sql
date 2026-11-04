-- Real SQL, synthetic expired-request fixture, all changes rolled back.
\set ON_ERROR_STOP on
BEGIN;
SET LOCAL timezone='UTC';
DO $test$
DECLARE cid uuid:='61b10574-c842-4dae-8e8b-647f0d51ba55'; old_id uuid:=gen_random_uuid();
    reviewer uuid; digest text; report_hash text; content_size integer; body text; old_body text;
    metadata text; report text; initial text; replacement text; result text; new_id uuid;
    created timestamptz:=statement_timestamp()-make_interval(secs=>86400);
    expires timestamptz:=statement_timestamp(); legacy_case uuid; legacy text; command text; i integer;
BEGIN
    IF current_database()<>'raa_wp2_validation'
       OR EXISTS(SELECT 1 FROM retail.approval_requests_v2)
       OR EXISTS(SELECT 1 FROM retail.approval_proposals) THEN RAISE EXCEPTION 'Pre-issuance validation database required'; END IF;
    SELECT reviewer_id,token_sha256 INTO STRICT reviewer,digest FROM retail.owner_credentials WHERE revoked_at IS NULL;
    metadata:=retail.api_get_case_v1(cid); report:=retail.api_get_revision_v1(cid,1);
    IF report IS NULL THEN RAISE EXCEPTION 'Retained real M02 report required'; END IF;
    report_hash:=encode(sha256(convert_to(report,'UTF8')),'hex'); content_size:=octet_length(convert_to(report,'UTF8'));
    body:=retail.approval_request_payload_v2(old_id,cid,1,report_hash,content_size,reviewer,
        created,expires,1,'wp4-expired-fixture-v2',NULL,NULL);
    old_body:=body;
    INSERT INTO retail.approval_requests_v2 VALUES(old_id,cid,1,1,'wp4-expired-fixture-v2',NULL,NULL,
        'local-publication-v1',reviewer,report_hash,content_size,created,expires,body,
        encode(sha256(convert_to(body,'UTF8')),'hex'));
    INSERT INTO retail.approval_request_events_v2(proposal_id,occurred_at) VALUES(old_id,created);
    EXECUTE 'SET LOCAL ROLE raa_wp2_case_api';
    initial:=retail.api_get_approval_request_v2(cid,old_id);
    IF initial::jsonb->>'review_status'<>'expired'
       OR (initial::jsonb#>>'{proposal,expires_at}')::timestamptz<>statement_timestamp() THEN
        RAISE EXCEPTION 'Exact exclusive expiry boundary failed';
    END IF;
    FOR i IN 1..10 LOOP
        result:=retail.api_issue_approval_request_v2(cid,1,report_hash,'wp4-expired-fixture-v2',NULL);
        IF result IS DISTINCT FROM initial THEN RAISE EXCEPTION 'Expired replay renewed request'; END IF;
    END LOOP;
    BEGIN PERFORM retail.api_issue_approval_request_v2(cid,1,report_hash,'wp4-wrong-predecessor',gen_random_uuid());
        RAISE EXCEPTION 'Wrong predecessor accepted'; EXCEPTION WHEN raise_exception THEN
        IF SQLERRM='Wrong predecessor accepted' THEN RAISE; END IF; END;
    BEGIN PERFORM retail.api_issue_approval_request_v2(cid,1,report_hash,'wp4-missing-predecessor',NULL);
        RAISE EXCEPTION 'Missing predecessor accepted'; EXCEPTION WHEN raise_exception THEN
        IF SQLERRM='Missing predecessor accepted' THEN RAISE; END IF; END;
    BEGIN PERFORM retail.api_issue_approval_request_v2(cid,2,report_hash,'wp4-invalid-version',old_id);
        RAISE EXCEPTION 'Wrong version accepted'; EXCEPTION WHEN invalid_parameter_value THEN NULL; END;
    replacement:=retail.api_issue_approval_request_v2(cid,1,report_hash,'wp4-replacement-fixture-v2',old_id);
    new_id:=(replacement::jsonb#>>'{proposal,proposal_id}')::uuid;
    IF new_id=old_id OR replacement::jsonb->>'proposal_sha256'=initial::jsonb->>'proposal_sha256'
       OR replacement::jsonb#>>'{proposal,generation}'<>'2'
       OR replacement::jsonb#>>'{proposal,predecessor_proposal_id}'<>old_id::text
       OR replacement::jsonb#>>'{proposal,predecessor_proposal_sha256}'<>initial::jsonb->>'proposal_sha256'
       OR (replacement::jsonb#>>'{proposal,expires_at}')::timestamptz
          -(replacement::jsonb#>>'{proposal,created_at}')::timestamptz<>make_interval(secs=>86400)
       OR replacement::jsonb#>>'{proposal,report_payload_sha256}'<>report_hash
       OR replacement::jsonb->>'decision_enabled'<>'false' THEN RAISE EXCEPTION 'Fresh immutable binding failed'; END IF;
    FOR i IN 1..10 LOOP
        result:=retail.api_issue_approval_request_v2(cid,1,report_hash,'wp4-replacement-fixture-v2',old_id);
        IF result IS DISTINCT FROM replacement THEN RAISE EXCEPTION 'Replacement replay changed deadline'; END IF;
    END LOOP;
    result:=retail.api_issue_approval_request_v2(cid,1,report_hash,'wp4-expired-fixture-v2',NULL);
    IF result::jsonb->>'canonical_payload_text'<>old_body OR result::jsonb->>'is_current'<>'false'
       OR result::jsonb->>'review_status'<>'expired' THEN RAISE EXCEPTION 'Predecessor history changed'; END IF;
    BEGIN PERFORM retail.api_issue_approval_request_v2(cid,1,report_hash,'wp4-active-predecessor',new_id);
        RAISE EXCEPTION 'Early replacement accepted'; EXCEPTION WHEN raise_exception THEN
        IF SQLERRM='Early replacement accepted' THEN RAISE; END IF; END;
    BEGIN PERFORM retail.api_issue_approval_request_v2(cid,1,report_hash,'wp4-replacement-fixture-v2',NULL);
        RAISE EXCEPTION 'Changed key binding accepted'; EXCEPTION WHEN raise_exception THEN
        IF SQLERRM='Changed key binding accepted' THEN RAISE; END IF; END;
    FOREACH command IN ARRAY ARRAY['SELECT * FROM retail.approval_requests_v2',
        'UPDATE retail.approval_requests_v2 SET expires_at=clock_timestamp()',
        'SELECT retail.api_prepare_approval_proposal_v1(gen_random_uuid(),1,repeat(''a'',64))'] LOOP
        BEGIN EXECUTE command; RAISE EXCEPTION 'Unexpected service privilege';
        EXCEPTION WHEN insufficient_privilege THEN NULL; END;
    END LOOP;
    EXECUTE 'RESET ROLE';
    IF (SELECT count(*) FROM retail.approval_requests_v2)<>2
       OR (SELECT count(*) FROM retail.approval_request_events_v2)<>2 THEN RAISE EXCEPTION 'Duplicate request/event'; END IF;
    FOREACH command IN ARRAY ARRAY['UPDATE retail.approval_requests_v2 SET expires_at=expires_at+interval ''1 second''',
        'DELETE FROM retail.approval_requests_v2','TRUNCATE retail.approval_request_events_v2'] LOOP
        BEGIN EXECUTE command; EXCEPTION WHEN raise_exception THEN CONTINUE; END;
        RAISE EXCEPTION 'Immutable history changed';
    END LOOP;
    EXECUTE 'SET LOCAL ROLE raa_wp4_reviewer_api';
    IF retail.api_owner_approval_request_v2(digest,cid,new_id) IS DISTINCT FROM replacement
       OR retail.api_owner_current_request_v2(digest,cid) IS DISTINCT FROM replacement THEN RAISE EXCEPTION 'Owner projection failed'; END IF;
    BEGIN PERFORM retail.api_owner_current_request_v2('invalid',gen_random_uuid());
        RAISE EXCEPTION 'Unknown owner accepted on empty case'; EXCEPTION WHEN insufficient_privilege THEN NULL; END;
    BEGIN PERFORM retail.api_issue_approval_request_v2(cid,1,report_hash,'wp4-owner-cannot-issue',new_id);
        RAISE EXCEPTION 'Owner acquired write grant'; EXCEPTION WHEN insufficient_privilege THEN NULL; END;
    EXECUTE 'RESET ROLE';
    SELECT case_id INTO STRICT legacy_case FROM retail.report_revisions WHERE case_id<>cid LIMIT 1;
    legacy:=retail.api_prepare_approval_proposal_v1(legacy_case,1,
        encode(sha256(convert_to(retail.api_get_revision_v1(legacy_case,1),'UTF8')),'hex'));
    EXECUTE 'SET LOCAL ROLE raa_wp2_case_api';
    BEGIN PERFORM retail.api_issue_approval_request_v2(legacy_case,1,
        encode(sha256(convert_to(retail.api_get_revision_v1(legacy_case,1),'UTF8')),'hex'),'wp4-legacy-transition',NULL);
        RAISE EXCEPTION 'Legacy silently replaced'; EXCEPTION WHEN raise_exception THEN
        IF SQLERRM='Legacy silently replaced' THEN RAISE; END IF; END;
    IF retail.api_get_approval_proposal_v1(legacy_case) IS DISTINCT FROM legacy THEN RAISE EXCEPTION 'Legacy bytes changed'; END IF;
    EXECUTE 'RESET ROLE';
    UPDATE retail.owner_credentials SET revoked_at=clock_timestamp() WHERE revoked_at IS NULL;
    EXECUTE 'SET LOCAL ROLE raa_wp2_case_api';
    BEGIN PERFORM retail.api_issue_approval_request_v2(cid,1,report_hash,'wp4-replacement-fixture-v2',old_id);
        RAISE EXCEPTION 'Revoked owner policy accepted'; EXCEPTION WHEN object_not_in_prerequisite_state THEN NULL; END;
    EXECUTE 'RESET ROLE';
    IF metadata IS DISTINCT FROM retail.api_get_case_v1(cid) OR report IS DISTINCT FROM retail.api_get_revision_v1(cid,1) THEN
        RAISE EXCEPTION 'Report/case changed';
    END IF;
    RAISE NOTICE 'PASS|exact-expiry|new-id-hash-deadline|two-ten-replays|retained-history|key-predecessor-conflicts|owner-reads|revocation|legacy-preserved|unchanged-report';
END $test$;
ROLLBACK;
