-- Staged dispatch contract. NOLOGIN, no worker, no API activation or file write.
DO $guard$ BEGIN
 IF current_database()<>'raa_wp2_validation'
   OR NOT EXISTS(SELECT 1 FROM retail.schema_migrations WHERE version=20)
   OR EXISTS(SELECT 1 FROM retail.schema_migrations WHERE version=21) THEN
  RAISE EXCEPTION 'Unapplied migration 021 / isolated migration 020 database required';
 END IF;
 IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='raa_wp4_dispatch_api') THEN
  CREATE ROLE raa_wp4_dispatch_api NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
   NOREPLICATION NOBYPASSRLS CONNECTION LIMIT 4;
 ELSIF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='raa_wp4_dispatch_api' AND NOT rolcanlogin
   AND NOT rolsuper AND NOT rolcreatedb AND NOT rolcreaterole AND NOT rolreplication AND NOT rolbypassrls)
   OR EXISTS(SELECT 1 FROM pg_auth_members WHERE roleid=(SELECT oid FROM pg_roles WHERE rolname='raa_wp4_dispatch_api')) THEN
  RAISE EXCEPTION 'Unactivated dispatch role required';
 END IF;
END $guard$;
GRANT CONNECT ON DATABASE raa_wp2_validation TO raa_wp4_dispatch_api;
GRANT USAGE ON SCHEMA retail TO raa_wp4_dispatch_api;
ALTER ROLE raa_wp4_dispatch_api IN DATABASE raa_wp2_validation SET statement_timeout='5s';
ALTER ROLE raa_wp4_dispatch_api IN DATABASE raa_wp2_validation SET lock_timeout='5s';
ALTER ROLE raa_wp4_dispatch_api IN DATABASE raa_wp2_validation SET default_transaction_read_only=on;

-- Immutable intent remains pending; execution state is this append-only ledger.
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
REVOKE ALL ON TABLE retail.publication_dispatch_events_v1 FROM PUBLIC;

CREATE FUNCTION retail.publication_authorized_v1(p_action uuid) RETURNS boolean
LANGUAGE sql VOLATILE SET search_path=pg_catalog,retail AS $function$
 SELECT coalesce((SELECT
  c.requester='local-service-v1' AND c.state='awaiting_approval' AND c.current_revision=a.report_revision
  AND d.outcome='approved' AND o.revoked_at IS NULL AND p.ttl_seconds=86400
  AND r.review_policy_version='local-publication-v1' AND clock_timestamp()>=r.created_at
  AND clock_timestamp()<r.expires_at AND a.authorization_expires_at=r.expires_at
  AND d.authorization_expires_at=r.expires_at AND d.reviewer_id=r.reviewer_id
  AND d.report_payload_sha256=a.content_sha256 AND d.proposal_sha256=a.proposal_sha256
  AND d.case_id=a.case_id AND d.report_revision=a.report_revision AND d.proposal_id=a.proposal_id
  AND e.event_type='review_approved' AND e.reviewer_id=d.reviewer_id AND e.occurred_at=d.decided_at
  AND d.payload_text=retail.decision_payload_v1(d.decision_id,d.case_id,d.proposal_id,d.report_revision,
    d.proposal_sha256,d.report_payload_sha256,d.reviewer_id,d.decision_key,d.outcome,d.decided_at,d.authorization_expires_at)
  AND r.payload_text=retail.approval_request_payload_v2(r.proposal_id,r.case_id,r.report_revision,
    r.report_payload_sha256,r.content_bytes,r.reviewer_id,r.created_at,r.expires_at,
    r.generation,r.request_key,r.predecessor_proposal_id,r.predecessor_proposal_sha256)
  AND r.payload_sha256=a.proposal_sha256 AND r.report_payload_sha256=a.content_sha256
  AND r.content_bytes=a.content_bytes AND report.payload_text=a.content_text
  AND report.payload_sha256=a.content_sha256
  AND encode(sha256(convert_to(a.content_text,'UTF8')),'hex')=a.content_sha256
  AND octet_length(convert_to(a.content_text,'UTF8'))=a.content_bytes
  AND a.action_key='publish-local-v1:'||r.proposal_id::text
  AND a.action_type='publish_local_report_json_v1' AND a.target_id='local-approved-report-json-v1'
  AND a.relative_path='reports/approved/v1/'||a.case_id::text||'/revision-1.json'
  AND a.action_payload_text=(r.payload_text::jsonb->'action')::text
  AND NOT EXISTS(SELECT 1 FROM retail.approval_requests_v2 n WHERE n.predecessor_proposal_id=r.proposal_id)
 FROM retail.publication_outbox_v1 a JOIN retail.review_decisions_v1 d USING(decision_id)
 JOIN retail.review_decision_events_v1 e USING(decision_id)
 JOIN retail.approval_requests_v2 r ON r.proposal_id=a.proposal_id
 JOIN retail.report_cases c ON c.case_id=a.case_id
 JOIN retail.report_revisions report ON (report.case_id,report.revision)=(a.case_id,a.report_revision)
 JOIN retail.owner_credentials o ON o.reviewer_id=d.reviewer_id
 JOIN retail.approval_policies p ON p.policy_version=r.review_policy_version AND p.reviewer_id=o.reviewer_id
 WHERE a.action_id=p_action),false);
$function$;

CREATE FUNCTION retail.lock_publication_v1(p_action uuid) RETURNS boolean
LANGUAGE plpgsql SET search_path=pg_catalog,retail AS $function$
DECLARE owner_id uuid; case_identity uuid;
BEGIN
 SELECT d.reviewer_id,a.case_id INTO owner_id,case_identity FROM retail.publication_outbox_v1 a
 JOIN retail.review_decisions_v1 d USING(decision_id) WHERE a.action_id=p_action;
 IF NOT FOUND THEN RAISE EXCEPTION 'Unknown action' USING ERRCODE='22023'; END IF;
 -- Same owner -> case ordering as decisions; revocation cannot pass a held lock.
 PERFORM 1 FROM retail.owner_credentials o WHERE o.reviewer_id=owner_id FOR SHARE NOWAIT;
 PERFORM 1 FROM retail.report_cases c WHERE c.case_id=case_identity FOR SHARE NOWAIT;
 PERFORM 1 FROM retail.publication_outbox_v1 a WHERE a.action_id=p_action FOR UPDATE NOWAIT;
 RETURN retail.publication_authorized_v1(p_action);
END $function$;

CREATE FUNCTION retail.guard_publication_dispatch_v1() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,retail AS $function$
DECLARE previous retail.publication_dispatch_events_v1%ROWTYPE; a retail.publication_outbox_v1%ROWTYPE;
 valid boolean; expected text; attempts integer; prior_state text;
BEGIN
 valid:=retail.lock_publication_v1(NEW.action_id);
 SELECT * INTO a FROM retail.publication_outbox_v1 WHERE action_id=NEW.action_id;
 SELECT * INTO previous FROM retail.publication_dispatch_events_v1 WHERE action_id=NEW.action_id ORDER BY sequence DESC LIMIT 1;
 attempts:=coalesce(previous.write_attempts,0); prior_state:=coalesce(previous.state,'pending');
 IF NEW.sequence<>coalesce(previous.sequence,0)+1 OR NEW.occurred_at>clock_timestamp()
   OR NEW.occurred_at<coalesce(previous.occurred_at,a.created_at)
   OR prior_state IN ('succeeded','cancelled','dead_letter') THEN
  RAISE EXCEPTION 'Dispatch history conflict' USING ERRCODE='55000';
 END IF;
 IF NEW.kind='claimed' THEN
  IF NEW.state<>'in_progress' OR NEW.lease_id IS NULL OR NEW.claim_key IS NULL
    OR NEW.lease_expires_at IS DISTINCT FROM NEW.occurred_at+interval '30 seconds'
    OR NEW.result IS NOT NULL OR NEW.observed_sha256 IS NOT NULL OR NEW.observed_bytes IS NOT NULL
    OR (prior_state='in_progress' AND clock_timestamp()<previous.lease_expires_at) THEN
   RAISE EXCEPTION 'Claim conflict' USING ERRCODE='55000';
  END IF;
  IF NEW.mode='write' THEN
   IF NOT valid OR prior_state<>'retryable' OR previous.mode<>'reconcile' OR previous.result<>'missing'
     OR attempts>=3 OR NEW.write_attempts<>attempts+1 THEN
    RAISE EXCEPTION 'Reconciled current authorization required' USING ERRCODE='55000';
   END IF;
  ELSIF NEW.write_attempts<>attempts THEN
   RAISE EXCEPTION 'Reconciliation cannot consume write attempt';
  END IF;
 ELSIF NEW.kind='observed' THEN
  IF previous.kind IS DISTINCT FROM 'claimed' OR NEW.lease_id IS DISTINCT FROM previous.lease_id
    OR clock_timestamp()>=previous.lease_expires_at OR NEW.mode<>previous.mode
    OR NEW.lease_expires_at IS NOT NULL OR NEW.claim_key IS NOT NULL OR NEW.result IS NULL
    OR NEW.write_attempts<>attempts THEN
   RAISE EXCEPTION 'Current live lease required' USING ERRCODE='55000';
  END IF;
  expected:=CASE NEW.result WHEN 'matching' THEN 'succeeded' WHEN 'unknown' THEN 'unknown'
   WHEN 'ambiguous' THEN 'dead_letter' ELSE CASE WHEN NEW.mode='write' THEN 'unknown'
    WHEN NOT valid THEN 'cancelled' WHEN attempts>=3 THEN 'dead_letter' ELSE 'retryable' END END;
  IF NEW.state<>expected OR (NEW.result='matching' AND
    (NEW.observed_sha256 IS DISTINCT FROM a.content_sha256 OR NEW.observed_bytes IS DISTINCT FROM a.content_bytes))
    OR (NEW.result<>'matching' AND (NEW.observed_sha256 IS NOT NULL OR NEW.observed_bytes IS NOT NULL)) THEN
   RAISE EXCEPTION 'Observation binding conflict' USING ERRCODE='22023';
  END IF;
 ELSE
  IF valid OR prior_state<>'retryable' OR previous.result<>'missing' OR previous.mode<>'reconcile'
    OR NEW.state<>'cancelled' OR NEW.mode<>'write' OR NEW.write_attempts<>attempts
    OR NEW.lease_id IS NOT NULL OR NEW.lease_expires_at IS NOT NULL OR NEW.claim_key IS NOT NULL
    OR NEW.result IS NOT NULL OR NEW.observed_sha256 IS NOT NULL OR NEW.observed_bytes IS NOT NULL THEN
   RAISE EXCEPTION 'Cancellation requires known missing target and invalid authorization';
  END IF;
 END IF;
 RETURN NEW;
END $function$;
CREATE TRIGGER publication_dispatch_binding BEFORE INSERT ON retail.publication_dispatch_events_v1
 FOR EACH ROW EXECUTE FUNCTION retail.guard_publication_dispatch_v1();
CREATE TRIGGER publication_dispatch_immutable BEFORE UPDATE OR DELETE ON retail.publication_dispatch_events_v1
 FOR EACH ROW EXECUTE FUNCTION retail.reject_source_mutation();
CREATE TRIGGER publication_dispatch_no_truncate BEFORE TRUNCATE ON retail.publication_dispatch_events_v1
 FOR EACH STATEMENT EXECUTE FUNCTION retail.reject_source_mutation();

CREATE FUNCTION retail.api_publication_state_v1(p_action uuid) RETURNS text
LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,retail AS $function$
 SELECT jsonb_build_object('action_id',a.action_id,'action_key',a.action_key,
  'case_id',a.case_id,'revision',a.report_revision,'state',coalesce(e.state,'pending'),
  'sequence',coalesce(e.sequence,0),'write_attempts',coalesce(e.write_attempts,0),
  'mode',e.mode,'lease_id',e.lease_id,'lease_expires_at',e.lease_expires_at,
  'lease_active',coalesce(e.kind='claimed' AND clock_timestamp()<e.lease_expires_at,false),
  'write_allowed',coalesce(e.kind='claimed' AND e.mode='write' AND clock_timestamp()<e.lease_expires_at
    AND retail.publication_authorized_v1(a.action_id),false),
  'target_id',a.target_id,'relative_path',a.relative_path,'content_sha256',a.content_sha256,
  'content_bytes',a.content_bytes,'authorization_expires_at',a.authorization_expires_at,
  'dispatch_enabled',false)::text
 FROM retail.publication_outbox_v1 a LEFT JOIN LATERAL
  (SELECT * FROM retail.publication_dispatch_events_v1 WHERE action_id=a.action_id ORDER BY sequence DESC LIMIT 1) e ON true
 WHERE a.action_id=p_action;
$function$;

CREATE FUNCTION retail.api_claim_publication_v1(p_action uuid,p_mode text,p_key text) RETURNS text
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,retail AS $function$
DECLARE valid boolean; previous retail.publication_dispatch_events_v1%ROWTYPE;
 old retail.publication_dispatch_events_v1%ROWTYPE; now_at timestamptz; body jsonb;
BEGIN
 IF p_mode IS NULL OR p_mode NOT IN ('write','reconcile') OR p_key IS NULL
   OR p_key COLLATE "C" !~ '^[A-Za-z0-9_-]{8,128}$' THEN RAISE EXCEPTION 'Invalid claim' USING ERRCODE='22023'; END IF;
 valid:=retail.lock_publication_v1(p_action);
 SELECT * INTO previous FROM retail.publication_dispatch_events_v1 WHERE action_id=p_action ORDER BY sequence DESC LIMIT 1;
 SELECT * INTO old FROM retail.publication_dispatch_events_v1 WHERE action_id=p_action AND claim_key=p_key;
 IF FOUND THEN
  IF old.mode<>p_mode THEN RAISE EXCEPTION 'Claim key conflict' USING ERRCODE='55000'; END IF;
  -- Historical same-key reads NEVER renew or return a replacement lease.
  body:=retail.api_publication_state_v1(p_action)::jsonb;
  IF old.event_id IS DISTINCT FROM previous.event_id THEN
   RETURN (body||jsonb_build_object('replayed_claim',true,'lease_id',old.lease_id,
    'lease_active',false,'write_allowed',false))::text;
  END IF;
 ELSE
  now_at:=clock_timestamp();
  IF p_mode='write' AND NOT valid AND previous.state='retryable' AND previous.mode='reconcile' AND previous.result='missing' THEN
   INSERT INTO retail.publication_dispatch_events_v1(action_id,sequence,kind,mode,state,write_attempts,occurred_at)
    VALUES(p_action,previous.sequence+1,'cancelled','write','cancelled',previous.write_attempts,now_at);
   RETURN retail.api_publication_state_v1(p_action);
  END IF;
  INSERT INTO retail.publication_dispatch_events_v1(action_id,sequence,kind,mode,state,write_attempts,
    lease_id,lease_expires_at,claim_key,occurred_at)
   VALUES(p_action,coalesce(previous.sequence,0)+1,'claimed',p_mode,'in_progress',
    coalesce(previous.write_attempts,0)+CASE WHEN p_mode='write' THEN 1 ELSE 0 END,
    gen_random_uuid(),now_at+interval '30 seconds',p_key,now_at);
  body:=retail.api_publication_state_v1(p_action)::jsonb;
 END IF;
 -- Content is available for exact read-only reconciliation even after expiry.
 -- A lease is not a credential; the unactivated DB grant is the trust boundary.
 IF (body->>'lease_active')::boolean THEN
  SELECT body||jsonb_build_object('content_text',a.content_text) INTO body FROM retail.publication_outbox_v1 a WHERE action_id=p_action;
 END IF;
 RETURN body::text;
END $function$;

CREATE FUNCTION retail.api_authorize_publication_v1(p_action uuid,p_lease uuid) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,retail AS $function$
DECLARE valid boolean; e retail.publication_dispatch_events_v1%ROWTYPE;
BEGIN
 valid:=retail.lock_publication_v1(p_action);
 SELECT * INTO e FROM retail.publication_dispatch_events_v1 WHERE action_id=p_action ORDER BY sequence DESC LIMIT 1;
 RETURN coalesce(valid AND p_lease=e.lease_id AND e.kind='claimed' AND e.mode='write'
  AND clock_timestamp()<e.lease_expires_at,false);
END $function$;

CREATE FUNCTION retail.api_observe_publication_v1(p_action uuid,p_lease uuid,p_result text,p_hash text,p_bytes integer) RETURNS text
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,retail AS $function$
DECLARE valid boolean; e retail.publication_dispatch_events_v1%ROWTYPE;
 old retail.publication_dispatch_events_v1%ROWTYPE; state text; now_at timestamptz;
BEGIN
 IF p_lease IS NULL OR p_result IS NULL OR p_result NOT IN ('matching','missing','unknown','ambiguous') THEN
  RAISE EXCEPTION 'Invalid observation' USING ERRCODE='22023'; END IF;
 valid:=retail.lock_publication_v1(p_action);
 SELECT * INTO e FROM retail.publication_dispatch_events_v1 WHERE action_id=p_action ORDER BY sequence DESC LIMIT 1;
 SELECT * INTO old FROM retail.publication_dispatch_events_v1 WHERE action_id=p_action AND lease_id=p_lease AND kind='observed';
 IF FOUND THEN
  IF old.result IS DISTINCT FROM p_result OR old.observed_sha256 IS DISTINCT FROM p_hash OR old.observed_bytes IS DISTINCT FROM p_bytes THEN
   RAISE EXCEPTION 'Observation replay conflict' USING ERRCODE='55000'; END IF;
  RETURN (retail.api_publication_state_v1(p_action)::jsonb||jsonb_build_object(
   'replayed_observation',true,'lease_id',old.lease_id,'lease_active',false,'write_allowed',false))::text;
 END IF;
 IF e.kind IS DISTINCT FROM 'claimed' OR e.lease_id IS DISTINCT FROM p_lease THEN
  RAISE EXCEPTION 'Current lease required' USING ERRCODE='55000'; END IF;
 state:=CASE p_result WHEN 'matching' THEN 'succeeded' WHEN 'unknown' THEN 'unknown' WHEN 'ambiguous' THEN 'dead_letter'
  ELSE CASE WHEN e.mode='write' THEN 'unknown' WHEN NOT valid THEN 'cancelled'
   WHEN e.write_attempts>=3 THEN 'dead_letter' ELSE 'retryable' END END;
 now_at:=clock_timestamp();
 INSERT INTO retail.publication_dispatch_events_v1(action_id,sequence,kind,mode,state,write_attempts,
   lease_id,result,observed_sha256,observed_bytes,occurred_at)
  VALUES(p_action,e.sequence+1,'observed',e.mode,state,e.write_attempts,p_lease,p_result,p_hash,p_bytes,now_at);
 RETURN retail.api_publication_state_v1(p_action);
END $function$;

REVOKE ALL ON FUNCTION retail.publication_authorized_v1(uuid),retail.lock_publication_v1(uuid),
 retail.guard_publication_dispatch_v1(),retail.api_publication_state_v1(uuid),
 retail.api_claim_publication_v1(uuid,text,text),retail.api_authorize_publication_v1(uuid,uuid),
 retail.api_observe_publication_v1(uuid,uuid,text,text,integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION retail.api_publication_state_v1(uuid),retail.api_claim_publication_v1(uuid,text,text),
 retail.api_authorize_publication_v1(uuid,uuid),retail.api_observe_publication_v1(uuid,uuid,text,text,integer)
 TO raa_wp4_dispatch_api;
INSERT INTO retail.schema_migrations(version,name) VALUES(21,'publication_dispatch_ledger');
