-- Durable isolated worker foundation. No main installation or old grant change.
DO $guard$
DECLARE role_name text;
BEGIN
 IF current_database() !~ '^raa_wp4_dispatch_test_[a-f0-9]{12}$'
  OR NOT EXISTS(SELECT 1 FROM retail.schema_migrations WHERE version=28)
  OR EXISTS(SELECT 1 FROM retail.schema_migrations WHERE version=29) THEN
  RAISE EXCEPTION 'Fresh isolated migration-028 database required'; END IF;
 FOREACH role_name IN ARRAY ARRAY['raa_wp4_portal_attempt_v1','raa_wp4_portal_recovery_v1'] LOOP
  IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname=role_name) THEN
   EXECUTE format('CREATE ROLE %I NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS',role_name);
  ELSIF EXISTS(SELECT 1 FROM pg_roles WHERE rolname=role_name AND
   (rolcanlogin OR rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication OR rolbypassrls))
   OR EXISTS(SELECT 1 FROM pg_auth_members m JOIN pg_roles r ON r.oid=m.roleid WHERE r.rolname=role_name) THEN
   RAISE EXCEPTION 'Unactivated scoped attempt role required'; END IF;
  EXECUTE format('GRANT CONNECT ON DATABASE %I TO %I',current_database(),role_name);
  EXECUTE format('GRANT USAGE ON SCHEMA retail TO %I',role_name);
 END LOOP;
END $guard$;

CREATE TABLE retail.portal_worker_events_v1 (
 event_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 action_id uuid NOT NULL REFERENCES retail.portal_publication_intents_v2(action_id),
 event_no integer NOT NULL CHECK(event_no>0),
 acceptance_key text NOT NULL CHECK(acceptance_key COLLATE "C" ~ '^[A-Za-z0-9_-]{8,128}$'),
 attempt_id uuid NOT NULL,
 reservation_xid xid8 NOT NULL DEFAULT pg_current_xact_id(),
 attempt_no integer NOT NULL CHECK(attempt_no BETWEEN 1 AND 3),
 attempt_key text NOT NULL CHECK(attempt_key COLLATE "C" ~ '^[A-Za-z0-9_-]{8,128}$'),
 execution_id text NOT NULL CHECK(execution_id COLLATE "C" ~ '^[1-9][0-9]{0,19}$'),
 kind text NOT NULL CHECK(kind IN ('reserved','accepted','reported','reconciled','operator_reconciled')),
 outcome text NOT NULL CHECK(outcome IN ('pending','committed','uncertain','retryable','permanent','expired','superseded','exhausted')),
 state text NOT NULL CHECK(state IN ('reserved','published','unknown','retryable','dead_letter','expired','superseded','exhausted')),
 occurred_at timestamptz NOT NULL CHECK(isfinite(occurred_at)),
 lease_expires_at timestamptz NOT NULL CHECK(isfinite(lease_expires_at)),
 recovery_key text CHECK(recovery_key COLLATE "C" ~ '^[A-Za-z0-9_-]{8,128}$'),
 actor_login name NOT NULL,
 UNIQUE(action_id,event_no),
 CHECK((kind='operator_reconciled')=(recovery_key IS NOT NULL))
);
CREATE UNIQUE INDEX portal_worker_reservation_key ON retail.portal_worker_events_v1(action_id,attempt_key) WHERE kind='reserved';
CREATE UNIQUE INDEX portal_worker_attempt_number ON retail.portal_worker_events_v1(action_id,attempt_no) WHERE kind='reserved';
CREATE UNIQUE INDEX portal_worker_attempt_identity ON retail.portal_worker_events_v1(attempt_id) WHERE kind='reserved';
CREATE UNIQUE INDEX portal_worker_recovery_key ON retail.portal_worker_events_v1(action_id,recovery_key) WHERE kind='operator_reconciled';
CREATE TRIGGER immutable BEFORE UPDATE OR DELETE ON retail.portal_worker_events_v1
 FOR EACH ROW EXECUTE FUNCTION retail.reject_source_mutation();
REVOKE ALL ON retail.portal_worker_events_v1 FROM PUBLIC;

-- All state changes serialize on the existing owner/case boundary. No caller
-- timestamp, lease duration, budget, new approval or publication receipt input.
CREATE FUNCTION retail.portal_attempt_context_v1(p_action uuid,p_key text) RETURNS jsonb
LANGUAGE plpgsql VOLATILE SET search_path=pg_catalog,retail SET timezone='UTC' AS $fn$
DECLARE saved jsonb; old retail.portal_worker_events_v1%ROWTYPE;
BEGIN
 saved:=retail.api_worker_portal_state_v2(p_action,p_key)::jsonb;
 IF saved IS NULL THEN RAISE EXCEPTION 'Approved outbox required' USING ERRCODE='P0002'; END IF;
 SELECT * INTO old FROM retail.portal_worker_events_v1 WHERE action_id=p_action ORDER BY event_no DESC LIMIT 1;
 IF FOUND AND old.acceptance_key IS DISTINCT FROM p_key THEN
  RAISE EXCEPTION 'Original durable key required' USING ERRCODE='55000'; END IF;
 RETURN saved;
END $fn$;

CREATE FUNCTION retail.portal_attempt_projection_v1(p_action uuid,p_key text) RETURNS text
LANGUAGE plpgsql VOLATILE SET search_path=pg_catalog,retail SET timezone='UTC' AS $fn$
DECLARE saved jsonb; old retail.portal_worker_events_v1%ROWTYPE; result_state text; now_at timestamptz;
BEGIN
 saved:=retail.portal_attempt_context_v1(p_action,p_key); now_at:=clock_timestamp();
 SELECT * INTO old FROM retail.portal_worker_events_v1 WHERE action_id=p_action ORDER BY event_no DESC LIMIT 1;
 result_state:=CASE WHEN saved#>'{snapshot,publication}'<>'null'::jsonb THEN 'published'
  WHEN NOT (saved#>>'{snapshot,is_current}')::boolean THEN 'superseded'
  WHEN now_at>=(saved#>>'{snapshot,request,expires_at}')::timestamptz THEN 'expired'
  WHEN old.state='reserved' AND now_at>=old.lease_expires_at THEN 'unknown'
  ELSE coalesce(old.state,'pending') END;
 RETURN jsonb_build_object('contract_version','portal-worker-attempt-state-v1','worker',saved,
  'ledger',jsonb_build_object('state',result_state,'attempt_count',coalesce(old.attempt_no,0),
   'max_attempts',3,'event_no',coalesce(old.event_no,0),'attempt_id',old.attempt_id,'attempt_key',old.attempt_key,
   'execution_id',old.execution_id,'lease_expires_at',old.lease_expires_at,'last_kind',old.kind,
   'reconciliation_required',old.state IN ('reserved','unknown'),
   'acceptance_key',p_key,'observed_at',now_at))::text;
END $fn$;

CREATE FUNCTION retail.portal_attempt_result_v1(p_saved jsonb,p_attempt_no integer,p_previous text,p_outcome text) RETURNS text
LANGUAGE sql VOLATILE SET search_path=pg_catalog,retail AS $fn$
 SELECT CASE WHEN p_saved#>'{snapshot,publication}'<>'null'::jsonb THEN 'published'
  WHEN NOT (p_saved#>>'{snapshot,is_current}')::boolean THEN 'superseded'
  WHEN clock_timestamp()>=(p_saved#>>'{snapshot,request,expires_at}')::timestamptz THEN 'expired'
  WHEN p_previous='dead_letter' OR p_outcome='permanent' THEN 'dead_letter'
  WHEN p_outcome='uncertain' THEN 'unknown'
  WHEN p_attempt_no>=3 THEN 'exhausted' ELSE 'retryable' END;
$fn$;

CREATE FUNCTION retail.guard_portal_worker_event_v1() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,retail AS $fn$
DECLARE old retail.portal_worker_events_v1%ROWTYPE; saved jsonb; now_at timestamptz;
BEGIN
 saved:=retail.portal_attempt_context_v1(NEW.action_id,NEW.acceptance_key);
 SELECT * INTO old FROM retail.portal_worker_events_v1 WHERE action_id=NEW.action_id ORDER BY event_no DESC LIMIT 1;
 now_at:=clock_timestamp(); NEW.occurred_at:=now_at; NEW.actor_login:=session_user;
 IF NEW.event_no IS DISTINCT FROM coalesce(old.event_no,0)+1 THEN
  RAISE EXCEPTION 'Ordered worker event required' USING ERRCODE='55000'; END IF;
 IF NEW.kind='reserved' THEN
  IF (old.event_id IS NOT NULL AND old.state<>'retryable')
   OR NEW.attempt_no IS DISTINCT FROM coalesce(old.attempt_no,0)+1
   OR NEW.outcome<>'pending' OR NEW.state<>'reserved'
   OR saved#>'{snapshot,publication}'<>'null'::jsonb
   OR NOT (saved#>>'{snapshot,is_current}')::boolean
   OR now_at>=(saved#>>'{snapshot,request,expires_at}')::timestamptz THEN
   RAISE EXCEPTION 'Fresh bounded reservation required' USING ERRCODE='55000'; END IF;
  NEW.lease_expires_at:=least(now_at+interval '30 seconds',(saved#>>'{snapshot,request,expires_at}')::timestamptz);
  NEW.reservation_xid:=pg_current_xact_id();
 ELSE
  IF old.event_id IS NULL OR NEW.attempt_id IS DISTINCT FROM old.attempt_id
   OR NEW.attempt_no IS DISTINCT FROM old.attempt_no OR NEW.attempt_key IS DISTINCT FROM old.attempt_key
   OR NEW.reservation_xid IS DISTINCT FROM old.reservation_xid
   OR NEW.execution_id IS DISTINCT FROM old.execution_id OR NEW.lease_expires_at IS DISTINCT FROM old.lease_expires_at THEN
   RAISE EXCEPTION 'Original attempt required' USING ERRCODE='55000'; END IF;
  IF NEW.kind='accepted' THEN
   IF old.state<>'reserved' OR NEW.state<>'published' OR NEW.outcome<>'committed'
    OR saved#>'{snapshot,publication}'='null'::jsonb THEN
    RAISE EXCEPTION 'Committed acceptance event required' USING ERRCODE='55000'; END IF;
  ELSIF NEW.kind='reported' THEN
   IF old.state<>'reserved' OR NEW.outcome NOT IN ('uncertain','retryable','permanent')
    OR NEW.state IS DISTINCT FROM retail.portal_attempt_result_v1(saved,old.attempt_no,old.state,NEW.outcome) THEN
    RAISE EXCEPTION 'Bound worker outcome required' USING ERRCODE='55000'; END IF;
  ELSIF NEW.kind IN ('reconciled','operator_reconciled') THEN
   IF (NEW.kind='reconciled' AND old.state NOT IN ('reserved','unknown'))
    OR (old.state='reserved' AND now_at<old.lease_expires_at AND saved#>'{snapshot,publication}'='null'::jsonb)
    OR NEW.state IS DISTINCT FROM retail.portal_attempt_result_v1(saved,old.attempt_no,old.state,'retryable')
    OR NEW.outcome IS DISTINCT FROM (CASE NEW.state WHEN 'published' THEN 'committed'
       WHEN 'dead_letter' THEN 'permanent' WHEN 'expired' THEN 'expired' WHEN 'superseded' THEN 'superseded'
       WHEN 'exhausted' THEN 'exhausted' ELSE 'retryable' END) THEN
    RAISE EXCEPTION 'Authoritative reconciliation required' USING ERRCODE='55000'; END IF;
  END IF;
 END IF;
 RETURN NEW;
END $fn$;
CREATE TRIGGER portal_worker_event_binding BEFORE INSERT ON retail.portal_worker_events_v1
 FOR EACH ROW EXECUTE FUNCTION retail.guard_portal_worker_event_v1();

CREATE FUNCTION retail.portal_append_attempt_event_v1(p_action uuid,p_key text,p_kind text,p_outcome text,p_state text,p_recovery text DEFAULT NULL)
RETURNS void LANGUAGE plpgsql VOLATILE SET search_path=pg_catalog,retail AS $fn$
DECLARE old retail.portal_worker_events_v1%ROWTYPE;
BEGIN
 SELECT * INTO STRICT old FROM retail.portal_worker_events_v1 WHERE action_id=p_action ORDER BY event_no DESC LIMIT 1;
 INSERT INTO retail.portal_worker_events_v1(action_id,event_no,acceptance_key,attempt_id,reservation_xid,attempt_no,attempt_key,execution_id,
  kind,outcome,state,occurred_at,lease_expires_at,recovery_key,actor_login)
 VALUES(p_action,old.event_no+1,p_key,old.attempt_id,old.reservation_xid,old.attempt_no,old.attempt_key,old.execution_id,
  p_kind,p_outcome,p_state,clock_timestamp(),old.lease_expires_at,p_recovery,session_user);
END $fn$;

CREATE FUNCTION retail.api_portal_attempt_state_v1(p_action uuid,p_key text) RETURNS text
LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,retail AS $fn$
 SELECT retail.portal_attempt_projection_v1(p_action,p_key);
$fn$;

CREATE FUNCTION retail.api_reserve_portal_attempt_v1(p_action uuid,p_key text,p_case uuid,p_request_sha text,p_report_sha text,
 p_attempt_key text,p_execution text) RETURNS text
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,retail AS $fn$
DECLARE saved jsonb; old retail.portal_worker_events_v1%ROWTYPE; replay retail.portal_worker_events_v1%ROWTYPE; projected jsonb;
BEGIN
 IF p_attempt_key IS NULL OR p_attempt_key COLLATE "C" !~ '^[A-Za-z0-9_-]{8,128}$'
  OR p_execution IS NULL OR p_execution COLLATE "C" !~ '^[1-9][0-9]{0,19}$' THEN
  RAISE EXCEPTION 'Exact execution identity required' USING ERRCODE='22023'; END IF;
 saved:=retail.portal_attempt_context_v1(p_action,p_key);
 IF p_case IS NULL OR p_case::text IS DISTINCT FROM saved#>>'{snapshot,request,case_id}'
  OR p_request_sha IS DISTINCT FROM saved#>>'{snapshot,request_sha256}'
  OR p_report_sha IS DISTINCT FROM saved#>>'{snapshot,request,report_payload_sha256}' THEN
  RAISE EXCEPTION 'Exact immutable attempt binding required' USING ERRCODE='55000'; END IF;
 SELECT * INTO replay FROM retail.portal_worker_events_v1 WHERE action_id=p_action AND kind='reserved' AND attempt_key=p_attempt_key;
 IF FOUND THEN
  IF replay.execution_id IS DISTINCT FROM p_execution THEN
   RAISE EXCEPTION 'Execution key conflict' USING ERRCODE='55000'; END IF;
  RETURN retail.portal_attempt_projection_v1(p_action,p_key);
 END IF;
 projected:=retail.portal_attempt_projection_v1(p_action,p_key)::jsonb;
 IF projected#>>'{ledger,state}' NOT IN ('pending','retryable') THEN RETURN projected::text; END IF;
 SELECT * INTO old FROM retail.portal_worker_events_v1 WHERE action_id=p_action ORDER BY event_no DESC LIMIT 1;
 INSERT INTO retail.portal_worker_events_v1(action_id,event_no,acceptance_key,attempt_id,attempt_no,attempt_key,execution_id,
  kind,outcome,state,occurred_at,lease_expires_at,actor_login)
 VALUES(p_action,coalesce(old.event_no,0)+1,p_key,gen_random_uuid(),coalesce(old.attempt_no,0)+1,p_attempt_key,p_execution,
  'reserved','pending','reserved',clock_timestamp(),clock_timestamp(),session_user);
 RETURN retail.portal_attempt_projection_v1(p_action,p_key);
END $fn$;

CREATE FUNCTION retail.api_accept_portal_attempt_v1(p_action uuid,p_key text,p_attempt uuid,p_execution text) RETURNS text
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,retail AS $fn$
DECLARE saved jsonb; old retail.portal_worker_events_v1%ROWTYPE;
BEGIN
 saved:=retail.portal_attempt_context_v1(p_action,p_key);
 SELECT * INTO old FROM retail.portal_worker_events_v1 WHERE action_id=p_action ORDER BY event_no DESC LIMIT 1;
 IF p_attempt IS NULL OR p_execution IS NULL OR old.attempt_id IS DISTINCT FROM p_attempt OR old.execution_id IS DISTINCT FROM p_execution THEN
  RAISE EXCEPTION 'Exact reserved attempt required' USING ERRCODE='55000'; END IF;
 IF pg_xact_status(old.reservation_xid) IS DISTINCT FROM 'committed' THEN
  RAISE EXCEPTION 'Committed reservation required' USING ERRCODE='55000'; END IF;
 IF saved#>'{snapshot,publication}'<>'null'::jsonb THEN
  IF old.state='reserved' THEN PERFORM retail.portal_append_attempt_event_v1(p_action,p_key,'accepted','committed','published'); END IF;
  RETURN retail.portal_attempt_projection_v1(p_action,p_key);
 END IF;
 IF old.state<>'reserved' OR clock_timestamp()>=old.lease_expires_at THEN
  RAISE EXCEPTION 'Live fenced reservation required' USING ERRCODE='55000'; END IF;
 -- Unchanged acceptance trigger owns the final fresh-clock deadline sample.
 PERFORM retail.api_accept_portal_publication_v2(p_action,p_key);
 PERFORM retail.portal_append_attempt_event_v1(p_action,p_key,'accepted','committed','published');
 RETURN retail.portal_attempt_projection_v1(p_action,p_key);
END $fn$;

CREATE FUNCTION retail.api_report_portal_attempt_v1(p_action uuid,p_key text,p_attempt uuid,p_execution text,p_outcome text) RETURNS text
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,retail AS $fn$
DECLARE saved jsonb; old retail.portal_worker_events_v1%ROWTYPE; result_state text;
BEGIN
 IF p_outcome IS NULL OR p_outcome NOT IN ('uncertain','retryable','permanent') THEN
  RAISE EXCEPTION 'Fixed outcome code required' USING ERRCODE='22023'; END IF;
 saved:=retail.portal_attempt_context_v1(p_action,p_key);
 SELECT * INTO old FROM retail.portal_worker_events_v1 WHERE action_id=p_action ORDER BY event_no DESC LIMIT 1;
 IF p_attempt IS NULL OR p_execution IS NULL OR old.attempt_id IS DISTINCT FROM p_attempt OR old.execution_id IS DISTINCT FROM p_execution THEN
  RAISE EXCEPTION 'Original reporting attempt required' USING ERRCODE='55000'; END IF;
 IF old.state='published' THEN RETURN retail.portal_attempt_projection_v1(p_action,p_key); END IF;
 IF old.kind='reported' AND old.outcome=p_outcome THEN RETURN retail.portal_attempt_projection_v1(p_action,p_key); END IF;
 IF old.state<>'reserved' THEN RAISE EXCEPTION 'Unsettled attempt required' USING ERRCODE='55000'; END IF;
 result_state:=retail.portal_attempt_result_v1(saved,old.attempt_no,old.state,p_outcome);
 PERFORM retail.portal_append_attempt_event_v1(p_action,p_key,'reported',p_outcome,result_state);
 RETURN retail.portal_attempt_projection_v1(p_action,p_key);
END $fn$;

CREATE FUNCTION retail.api_reconcile_portal_attempt_v1(p_action uuid,p_key text) RETURNS text
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,retail AS $fn$
DECLARE saved jsonb; old retail.portal_worker_events_v1%ROWTYPE; result_state text; result_outcome text;
BEGIN
 saved:=retail.portal_attempt_context_v1(p_action,p_key);
 SELECT * INTO old FROM retail.portal_worker_events_v1 WHERE action_id=p_action ORDER BY event_no DESC LIMIT 1;
 IF old.event_id IS NULL OR old.state NOT IN ('reserved','unknown') THEN RETURN retail.portal_attempt_projection_v1(p_action,p_key); END IF;
 IF old.state='reserved' AND clock_timestamp()<old.lease_expires_at AND saved#>'{snapshot,publication}'='null'::jsonb THEN
  RAISE EXCEPTION 'Live reservation cannot be recovered' USING ERRCODE='55000'; END IF;
 result_state:=retail.portal_attempt_result_v1(saved,old.attempt_no,old.state,'retryable');
 result_outcome:=CASE result_state WHEN 'published' THEN 'committed' WHEN 'expired' THEN 'expired'
  WHEN 'superseded' THEN 'superseded' WHEN 'exhausted' THEN 'exhausted' ELSE 'retryable' END;
 PERFORM retail.portal_append_attempt_event_v1(p_action,p_key,'reconciled',result_outcome,result_state);
 RETURN retail.portal_attempt_projection_v1(p_action,p_key);
END $fn$;

CREATE FUNCTION retail.api_operator_reconcile_portal_v1(p_action uuid,p_key text,p_recovery text) RETURNS text
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,retail AS $fn$
DECLARE saved jsonb; old retail.portal_worker_events_v1%ROWTYPE; result_state text; result_outcome text;
BEGIN
 IF p_recovery IS NULL OR p_recovery COLLATE "C" !~ '^[A-Za-z0-9_-]{8,128}$' THEN
  RAISE EXCEPTION 'Explicit recovery key required' USING ERRCODE='22023'; END IF;
 saved:=retail.portal_attempt_context_v1(p_action,p_key);
 SELECT * INTO old FROM retail.portal_worker_events_v1 WHERE action_id=p_action ORDER BY event_no DESC LIMIT 1;
 IF old.event_id IS NULL THEN RAISE EXCEPTION 'Existing attempt required' USING ERRCODE='55000'; END IF;
 IF EXISTS(SELECT 1 FROM retail.portal_worker_events_v1 WHERE action_id=p_action AND recovery_key=p_recovery) THEN
  RETURN retail.portal_attempt_projection_v1(p_action,p_key); END IF;
 IF (SELECT count(*) FROM retail.portal_worker_events_v1 WHERE action_id=p_action AND kind='operator_reconciled')>=20 THEN
  RAISE EXCEPTION 'Bounded recovery history required' USING ERRCODE='55000'; END IF;
 IF old.state='reserved' AND clock_timestamp()<old.lease_expires_at AND saved#>'{snapshot,publication}'='null'::jsonb THEN
  RAISE EXCEPTION 'Live reservation cannot be recovered' USING ERRCODE='55000'; END IF;
 result_state:=retail.portal_attempt_result_v1(saved,old.attempt_no,old.state,'retryable');
 result_outcome:=CASE result_state WHEN 'published' THEN 'committed' WHEN 'dead_letter' THEN 'permanent'
  WHEN 'expired' THEN 'expired' WHEN 'superseded' THEN 'superseded' WHEN 'exhausted' THEN 'exhausted' ELSE 'retryable' END;
 PERFORM retail.portal_append_attempt_event_v1(p_action,p_key,'operator_reconciled',result_outcome,result_state,p_recovery);
 RETURN retail.portal_attempt_projection_v1(p_action,p_key);
END $fn$;

DO $permissions$
DECLARE fn record;
BEGIN
 FOR fn IN SELECT p.oid::regprocedure AS signature FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
  WHERE n.nspname='retail' AND p.proname IN ('portal_attempt_context_v1','portal_attempt_projection_v1',
   'portal_attempt_result_v1','guard_portal_worker_event_v1','portal_append_attempt_event_v1','api_portal_attempt_state_v1',
   'api_reserve_portal_attempt_v1','api_accept_portal_attempt_v1','api_report_portal_attempt_v1',
   'api_reconcile_portal_attempt_v1','api_operator_reconcile_portal_v1') LOOP
  EXECUTE format('REVOKE ALL ON FUNCTION %s FROM PUBLIC',fn.signature);
 END LOOP;
END $permissions$;
GRANT EXECUTE ON FUNCTION retail.api_portal_attempt_state_v1(uuid,text),
 retail.api_reserve_portal_attempt_v1(uuid,text,uuid,text,text,text,text),
 retail.api_accept_portal_attempt_v1(uuid,text,uuid,text),retail.api_report_portal_attempt_v1(uuid,text,uuid,text,text),
 retail.api_reconcile_portal_attempt_v1(uuid,text) TO raa_wp4_portal_attempt_v1;
GRANT EXECUTE ON FUNCTION retail.api_operator_reconcile_portal_v1(uuid,text,text) TO raa_wp4_portal_recovery_v1;
INSERT INTO retail.schema_migrations(version,name) VALUES(29,'portal_worker_attempts');
