"""Fresh schema-only dispatch DB; synthetic credentials/intents, no file writes."""
import argparse
from hashlib import sha256
import json
import secrets
from uuid import uuid4
from wp2_api_local import ROOT,docker
from wp4_portal_local import retain


def provision():
    database='raa_wp4_dispatch_test_'+uuid4().hex[:12]
    login='raa_wp4_dispatch_test_'+uuid4().hex[:12]
    password=secrets.token_hex(32)
    owner=secrets.token_hex(32)
    retain(password); retain(owner)
    admin_password=docker(['exec','raa-g0-postgres-1','printenv','POSTGRES_PASSWORD'])
    if not admin_password or any(c in admin_password for c in '\r\n'):
        raise RuntimeError('Configured database required')
    schema=docker(['exec','raa-g0-postgres-1','pg_dump','-U','g0_user','-d','raa_wp2_validation','--schema-only','--schema=retail'])
    base=json.loads(docker(['exec','raa-g0-postgres-1','psql','-X','-qAt','-U','g0_user','-d','raa_wp2_validation','-c',
        "SELECT jsonb_build_object('request',request_identity,'report',retail.api_get_revision_v1(case_id,1)) "
        "FROM retail.report_cases WHERE case_id='61b10574-c842-4dae-8e8b-647f0d51ba55';"]))
    migration=(ROOT/'db/migrations/021_publication_dispatch_ledger.sql').read_text(encoding='utf-8')
    if migration.count('raa_wp2_validation')!=5 or schema.find('publication_dispatch_events_v1')!=-1:
        raise RuntimeError('Unapplied isolated dispatch stage required')
    docker(['exec','raa-g0-postgres-1','createdb','-U','g0_user',database])
    print('Isolated schema-only database created: '+database)
    def sql(value):
        return docker(['exec','-i','raa-g0-postgres-1','psql','-X','-q','-v','ON_ERROR_STOP=1','-1','-U','g0_user','-d',database,'-f','-'],value)
    sql(schema)
    sql("INSERT INTO retail.schema_migrations(version,name) VALUES(20,'portal_decision_projection');")
    sql(migration.replace('raa_wp2_validation',database))
    print('PASS|isolated-migration-021|NOLOGIN|real-database-not-migrated')
    sql("CREATE ROLE "+login+" LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS "
        "CONNECTION LIMIT 4 PASSWORD '"+password+"'; GRANT CONNECT ON DATABASE "+database+" TO "+login+"; "
        "GRANT USAGE ON SCHEMA retail TO "+login+"; ALTER ROLE "+login+" IN DATABASE "+database+" SET default_transaction_read_only=on; "
        "ALTER ROLE "+login+" IN DATABASE "+database+" SET statement_timeout='5s'; "
        "GRANT EXECUTE ON FUNCTION retail.api_publication_state_v1(uuid),retail.api_claim_publication_v1(uuid,text,text),"
        "retail.api_authorize_publication_v1(uuid,uuid),retail.api_observe_publication_v1(uuid,uuid,text,text,integer) TO "+login+";")
    fixture=(ROOT/'db/tests/019_decision_outbox_foundation.sql').read_text(encoding='utf-8').split('DO $test$')[0]
    fixture='\n'.join(line for line in fixture.splitlines() if not line.startswith('\\'))
    config={'database':database,'admin':{'host':'raa-g0-postgres-1','dbname':database,'user':'g0_user','password':admin_password},
        'worker':{'host':'raa-g0-postgres-1','dbname':database,'user':login,'password':password},
        'owner_hash':sha256(owner.encode()).hexdigest(),'fixture_sql':fixture,'base':base}
    return config


def main(adapter=False):
    config=provision()
    database=config['database']
    test='test_wp4_dispatch_adapter_database.py' if adapter else 'test_wp4_dispatch_database.py'
    result=json.loads(docker(['exec','-i','raa-wp2-api','python','-c',
        "import sys,runpy; sys.path.insert(0,'/app/tests'); runpy.run_path('/app/tests/"+test+"',run_name='__main__')"],json.dumps(config)))
    print('Test database and restricted test login retained: '+database)
    if not result.get('passed'):
        print('FAIL|dispatch-tests|'+str(result.get('tests_run',0))+'|'+','.join(result.get('failed_tests',[])))
        print('FAIL|exception-types|'+','.join(result.get('error_types',[])))
        raise RuntimeError('Isolated dispatch tests failed')
    print('PASS|dispatch-tests|'+str(result['tests_run'])+'|actual-login|concurrency|exclusive-expiry|lease-recovery|'+
        ('coordinator-memory-files-NOT-NTFS' if adapter else 'no-files'))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--adapter',action='store_true',help='Test coordinator with real SQL and in-memory file double (not NTFS)')
    args=parser.parse_args()
    try: main(args.adapter)
    except (RuntimeError,ValueError,OSError):
        raise SystemExit('FAIL|dispatch-check|details-suppressed-to-protect-secrets') from None
