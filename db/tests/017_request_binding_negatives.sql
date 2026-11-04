-- No source facts/credentials are changed; candidate request inserts rollback.
\set ON_ERROR_STOP on
BEGIN;
SET LOCAL timezone='UTC';
DO $test$
DECLARE cid uuid; reviewer uuid; payload text; body text; bad_body text; identifier uuid:=gen_random_uuid();
    report_hash text; size integer; created timestamptz:=clock_timestamp(); expires timestamptz;
    rejected boolean; mode integer;
BEGIN
    SELECT r.case_id INTO STRICT cid FROM retail.report_revisions r
        WHERE NOT EXISTS(SELECT 1 FROM retail.approval_requests_v2 a WHERE a.case_id=r.case_id)
        AND NOT EXISTS(SELECT 1 FROM retail.approval_proposals a WHERE a.case_id=r.case_id) LIMIT 1;
    SELECT reviewer_id INTO STRICT reviewer FROM retail.owner_credentials WHERE revoked_at IS NULL;
    payload:=retail.api_get_revision_v1(cid,1);
    report_hash:=encode(sha256(convert_to(payload,'UTF8')),'hex'); size:=octet_length(convert_to(payload,'UTF8'));
    expires:=created+make_interval(secs=>86400);
    body:=retail.approval_request_payload_v2(identifier,cid,1,report_hash,size,reviewer,
        created,expires,1,'wp4-binding-fixture-v2',NULL,NULL);
    -- Valid control succeeds, then this subtransaction deliberately rolls it
    -- back so every negative tests the actual binding, not a duplicate key.
    BEGIN
        INSERT INTO retail.approval_requests_v2 VALUES(identifier,cid,1,1,'wp4-binding-fixture-v2',NULL,NULL,
            'local-publication-v1',reviewer,report_hash,size,created,expires,body,
            encode(sha256(convert_to(body,'UTF8')),'hex'));
        RAISE EXCEPTION 'Control-only rollback';
    EXCEPTION WHEN raise_exception THEN IF SQLERRM<>'Control-only rollback' THEN RAISE; END IF; END;
    FOR mode IN 1..16 LOOP
        bad_body:=CASE mode
            WHEN 6 THEN jsonb_set(body::jsonb,'{action,target,relative_path}','"../outside.json"')::text
            WHEN 7 THEN jsonb_set(body::jsonb,'{generation}','2')::text
            WHEN 10 THEN jsonb_set(body::jsonb,'{canonicalization}','"caller-format"')::text
            WHEN 14 THEN NULL
            WHEN 15 THEN jsonb_set(body::jsonb,'{source_file_sha256}','"caller-source"')::text
            WHEN 16 THEN jsonb_set(body::jsonb,'{request_key}','"changed-key"')::text
            ELSE body END;
        rejected:=false;
        BEGIN
            INSERT INTO retail.approval_requests_v2 VALUES(identifier,cid,1,1,
                CASE WHEN mode=11 THEN 'invalid key' ELSE 'wp4-binding-fixture-v2' END,
                CASE WHEN mode=8 THEN gen_random_uuid() ELSE NULL END,NULL,
                'local-publication-v1',CASE WHEN mode=2 THEN gen_random_uuid() WHEN mode=13 THEN NULL ELSE reviewer END,
                CASE WHEN mode=1 THEN repeat('0',64) ELSE report_hash END,
                CASE WHEN mode=3 THEN size+1 ELSE size END,
                CASE WHEN mode=4 THEN created+interval '1 day' WHEN mode=12 THEN NULL ELSE created END,
                CASE WHEN mode=5 THEN expires+interval '1 second' ELSE expires END,bad_body,
                CASE WHEN mode=9 THEN repeat('0',64) ELSE encode(sha256(convert_to(bad_body,'UTF8')),'hex') END);
        EXCEPTION WHEN raise_exception OR check_violation OR not_null_violation OR foreign_key_violation THEN rejected:=true; END;
        IF NOT rejected THEN RAISE EXCEPTION 'Binding mutation accepted'; END IF;
    END LOOP;
    IF EXISTS(SELECT 1 FROM retail.approval_requests_v2 WHERE case_id=cid) THEN RAISE EXCEPTION 'Unexpected retained test row'; END IF;
    RAISE NOTICE 'PASS|valid-control|16-body-column-null-hash-target-source-key-tamper-denials|no-retained-test-rows';
END $test$;
ROLLBACK;
