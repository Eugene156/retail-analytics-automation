"""Private test IPC inside existing API container. Not an application endpoint."""
import json
import re
import sys
import psycopg

LIMIT=1048576
QUERIES={
    'database': ('SELECT current_database()', 0),
    'state': ('SELECT retail.api_publication_state_v1(%s)', 1),
    'claim': ('SELECT retail.api_claim_publication_v1(%s,%s,%s)', 3),
    'authorize': ('SELECT retail.api_authorize_publication_v1(%s,%s)', 2),
    'observe': ('SELECT retail.api_observe_publication_v1(%s,%s,%s,%s,%s)', 5),
}


def read():
    line=sys.stdin.readline(LIMIT+1)
    if not line: return None
    if len(line)>LIMIT or not line.endswith('\n'): raise ValueError('Bounded private frame required')
    value=json.loads(line)
    if not isinstance(value,dict): raise ValueError('Object required')
    return value


def reply(value):
    print(json.dumps({'ok':True,'value':value}),flush=True)


def validate(config):
    db=config.get('database')
    if not isinstance(db,str) or not re.fullmatch(r'raa_wp4_dispatch_test_[a-f0-9]{12}',db):
        raise ValueError('Isolated DB required')
    worker=config['worker']
    if set(worker)!={'host','dbname','user','password'} or worker['host']!='raa-g0-postgres-1' \
            or worker['dbname']!=db or not re.fullmatch(r'raa_wp4_dispatch_test_[a-f0-9]{12}',worker['user']):
        raise ValueError('Fixed isolated worker required')
    return db


def worker(config):
    db=validate(config)
    conn=psycopg.connect(**config['worker'])
    try:
        if conn.execute('SELECT current_database()').fetchone()[0]!=db: raise ValueError('Wrong DB')
        conn.rollback()
        reply({'database':db,'autocommit':conn.autocommit})
        while True:
            request=read()
            if request is None: break
            op=request.get('op'); args=request.get('args',[])
            try:
                if op in QUERIES:
                    sql,count=QUERIES[op]
                    if set(request)!={'op','args'} or not isinstance(args,list) or len(args)!=count:
                        raise ValueError('Fixed query arguments required')
                    reply(conn.execute(sql,tuple(args)).fetchone()[0])
                elif set(request)=={'op'} and op in ('rollback','commit','write','close'):
                    if op=='close': reply(None); break
                    if op=='write': conn.read_only=False
                    elif op=='commit': conn.commit()
                    else: conn.rollback()
                    reply(None)
                else: raise ValueError('Unknown operation')
            except Exception:
                # Keep transaction status unchanged for explicit caller rollback.
                print('{"ok":false,"error":"operation-denied"}',flush=True)
    finally:
        conn.rollback(); conn.close()


def controller(config):
    db=validate(config)
    admin=config['admin']
    if set(admin)!={'host','dbname','user','password'} or admin['host']!='raa-g0-postgres-1' \
            or admin['dbname']!=db or admin['user']!='g0_user': raise ValueError('Fixed fixture DB required')
    import test_wp4_dispatch_database as foundation
    foundation.CONFIG=config
    cls=foundation.DispatchDatabaseTests
    cls.setUpClass()
    fixture=cls('test_reject_and_expire_never_create_intents')
    conn=cls.admin
    fault=False
    try:
        short=config['fixture_sql'].split('CREATE FUNCTION pg_temp.decide_fixture_v1')[0]
        short=short.replace('review_fixture_v1','native_short_fixture_v1').replace('ELSE clock_timestamp() END',
            "ELSE clock_timestamp()-interval '23 hours 59 minutes 42 seconds' END")
        conn.execute(short); conn.commit()
        reply({'database':db})
        while True:
            request=read()
            if request is None: break
            try:
                if set(request)!={'op'}: raise ValueError('No fixture overrides')
                op=request['op']
                if op=='fixture': reply(fixture.fixture())
                elif op=='short_fixture':
                    f=conn.execute('SELECT pg_temp.native_short_fixture_v1(false)').fetchone()[0]
                    value=conn.execute('SELECT pg_temp.decide_fixture_v1(%s::jsonb,%s,%s)',
                        (json.dumps(f),'approve','native-decision-'+__import__('uuid').uuid4().hex)).fetchone()[0]
                    conn.commit(); reply(json.loads(value)['outbox'])
                elif op=='revoke':
                    conn.execute('UPDATE retail.owner_credentials SET revoked_at=clock_timestamp() WHERE reviewer_id=%s',(cls.owner,))
                    conn.commit(); reply(None)
                elif op=='fault_on':
                    conn.execute("CREATE FUNCTION pg_temp.native_receipt_fault() RETURNS trigger LANGUAGE plpgsql AS $$ "
                        "BEGIN IF NEW.kind='observed' THEN RAISE EXCEPTION 'Synthetic receipt fault'; END IF; RETURN NEW; END $$")
                    conn.execute('CREATE TRIGGER native_receipt_fault AFTER INSERT ON retail.publication_dispatch_events_v1 '
                        'FOR EACH ROW EXECUTE FUNCTION pg_temp.native_receipt_fault()')
                    conn.commit(); fault=True; reply(None)
                elif op=='fault_off':
                    conn.execute('DROP TRIGGER native_receipt_fault ON retail.publication_dispatch_events_v1')
                    conn.commit(); fault=False; reply(None)
                elif op=='counts':
                    counts=conn.execute('SELECT (SELECT count(*) FROM retail.source_rows),'
                        '(SELECT count(*) FROM retail.publication_outbox_v1),'
                        '(SELECT count(*) FROM retail.publication_dispatch_events_v1)') .fetchone()
                    conn.rollback(); reply(list(counts))
                elif op=='close': reply(None); break
                else: raise ValueError('Unknown fixture operation')
            except Exception:
                conn.rollback(); print('{"ok":false,"error":"fixture-denied"}',flush=True)
    finally:
        if fault:
            conn.rollback()
            conn.execute('DROP TRIGGER native_receipt_fault ON retail.publication_dispatch_events_v1'); conn.commit()
        cls.tearDownClass()


if __name__=='__main__':
    try:
        config=read()
        if config.get('kind')=='worker': worker(config)
        elif config.get('kind')=='controller': controller(config)
        else: raise ValueError('Fixed IPC role required')
    except Exception:
        print('{"ok":false,"error":"private-ipc-failed"}',flush=True)
        raise SystemExit(1) from None
