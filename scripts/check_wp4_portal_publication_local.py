"""New portal-target SQL foundation, fresh schema-only database, no file effects."""
import argparse
from hashlib import sha256
import hmac
import json
import re
import secrets
import time
from uuid import uuid4

from check_wp4_dispatch_local import provision
from wp2_api_local import ROOT, docker
from wp4_portal_local import retain, retain_many


def provision_portal(reads=False, forms=False, transition=False, transition_api=False, auth=False, worker=False, attempts=False, attempt_api=False):
    attempts = attempts or attempt_api
    worker = worker or attempts
    auth = auth or worker
    transition_api = transition_api or auth
    transition = transition or transition_api
    forms = forms or transition
    reads = reads or forms
    config = provision()
    database = config['database']
    if not re.fullmatch(r'raa_wp4_dispatch_test_[a-f0-9]{12}', database):
        raise RuntimeError('Generated isolated database required')
    migration = (ROOT / 'db/migrations/022_portal_publication_foundation.sql').read_text(encoding='utf-8')
    docker(['exec', '-i', 'raa-g0-postgres-1', 'psql', '-X', '-q', '-1', '-v',
            'ON_ERROR_STOP=1', '-U', 'g0_user', '-d', database, '-f', '-'], migration)
    print('PASS|isolated-migration-022|NOLOGIN|main-not-migrated')
    # Synthetic session/CSRF digests are sensitive too. Register before testing
    # so the existing private log scan covers them without printing values.
    config['sessions'] = []
    for _ in range(120 if transition else 40):
        session, csrf = secrets.token_hex(32), secrets.token_hex(32)
        retain(session); retain(csrf)
        config['sessions'].append((session, csrf))
    if reads:
        migration = (ROOT / 'db/migrations/023_portal_publication_reads.sql').read_text(encoding='utf-8')
        docker(['exec', '-i', 'raa-g0-postgres-1', 'psql', '-X', '-q', '-1', '-v',
                'ON_ERROR_STOP=1', '-U', 'g0_user', '-d', database, '-f', '-'], migration)
        print('PASS|isolated-migration-023|NOLOGIN|main-not-migrated')
        if forms:
            migration = (ROOT / 'db/migrations/024_portal_review_projections.sql').read_text(encoding='utf-8')
            docker(['exec', '-i', 'raa-g0-postgres-1', 'psql', '-X', '-q', '-1', '-v',
                    'ON_ERROR_STOP=1', '-U', 'g0_user', '-d', database, '-f', '-'], migration)
            print('PASS|isolated-migration-024|NOLOGIN|main-not-migrated')
            config['service_token'], config['portal_key'] = secrets.token_hex(32), secrets.token_hex(32)
            retain(config['service_token']); retain(config['portal_key'])
            if transition:
                migration = (ROOT / 'db/migrations/025_portal_legacy_transition.sql').read_text(encoding='utf-8')
                docker(['exec', '-i', 'raa-g0-postgres-1', 'psql', '-X', '-q', '-1', '-v',
                        'ON_ERROR_STOP=1', '-U', 'g0_user', '-d', database, '-f', '-'], migration)
                print('PASS|isolated-migration-025|NOLOGIN|main-not-migrated')
                if transition_api:
                    migration = (ROOT / 'db/migrations/026_portal_transition_reads.sql').read_text(encoding='utf-8')
                    docker(['exec', '-i', 'raa-g0-postgres-1', 'psql', '-X', '-q', '-1', '-v',
                            'ON_ERROR_STOP=1', '-U', 'g0_user', '-d', database, '-f', '-'], migration)
                    print('PASS|isolated-migration-026|NOLOGIN|main-not-migrated')
                    if auth:
                        migration = (ROOT / 'db/migrations/027_portal_auth_v2.sql').read_text(encoding='utf-8')
                        docker(['exec', '-i', 'raa-g0-postgres-1', 'psql', '-X', '-q', '-1', '-v',
                                'ON_ERROR_STOP=1', '-U', 'g0_user', '-d', database, '-f', '-'], migration)
                        print('PASS|isolated-migration-027|NOLOGIN|main-not-migrated')
                        if worker:
                            migration = (ROOT / 'db/migrations/028_portal_worker_boundary.sql').read_text(encoding='utf-8')
                            docker(['exec', '-i', 'raa-g0-postgres-1', 'psql', '-X', '-q', '-1', '-v',
                                    'ON_ERROR_STOP=1', '-U', 'g0_user', '-d', database, '-f', '-'], migration)
                            print('PASS|isolated-migration-028|NOLOGIN|main-not-migrated')
                            if attempts:
                                migration = (ROOT / 'db/migrations/029_portal_worker_attempts.sql').read_text(encoding='utf-8')
                                docker(['exec', '-i', 'raa-g0-postgres-1', 'psql', '-X', '-q', '-1', '-v',
                                        'ON_ERROR_STOP=1', '-U', 'g0_user', '-d', database, '-f', '-'], migration)
                                print('PASS|isolated-migration-029|NOLOGIN|main-not-migrated')
        config['browser_sessions'] = []
        for _ in range(40):
            raw = secrets.token_hex(32)
            csrf = hmac.new(bytes.fromhex(raw), b'raa-portal-csrf-v1', 'sha256').hexdigest()
            retain(raw); retain(csrf)
            config['browser_sessions'].append(raw)
    if auth:
        # Test-only entropy/clock injection keeps all generated cookies/challenges
        # registered BEFORE use, without exposing any secret in argv or output.
        config['owner_token'] = secrets.token_hex(32)
        retain(config['owner_token'])
        config['owner_hash'] = sha256(config['owner_token'].encode('ascii')).hexdigest()
        config['auth_clock'] = int(time.time())
        config['auth_random'] = []
        probes = []
        for _ in range(256):
            raw = secrets.token_hex(32)
            probes.append(raw)
            probes.append(hmac.new(bytes.fromhex(raw), b'raa-portal-csrf-v1', 'sha256').hexdigest())
            config['auth_random'].append(raw)
            for offset in (0, -300, -301, 1):
                unsigned = raw + '.' + str(config['auth_clock'] + offset)
                probes.append(unsigned + '.' + hmac.new(bytes.fromhex(config['portal_key']), unsigned.encode(), 'sha256').hexdigest())
        retain_many(probes)
    statements = []
    for kind, signature in (
            ('issuer', 'retail.api_issue_portal_request_v3(uuid,text,text,uuid)'),
            ('reviewer', 'retail.api_decide_portal_request_v2(text,text,uuid,text,text,text)')):
        login = 'raa_wp4_portal_test_' + uuid4().hex[:12]
        password = secrets.token_hex(32)
        retain(password)
        config[kind] = dict(config['worker'], user=login, password=password)
        statements.append(
            f"CREATE ROLE {login} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS "
            f"CONNECTION LIMIT 4 PASSWORD '{password}'; GRANT CONNECT ON DATABASE {database} TO {login}; "
            f"GRANT USAGE ON SCHEMA retail TO {login}; ALTER ROLE {login} IN DATABASE {database} "
            f"SET default_transaction_read_only=on; ALTER ROLE {login} IN DATABASE {database} "
            f"SET statement_timeout='5s'; GRANT EXECUTE ON FUNCTION {signature} TO {login};")
    legacy_worker_login = config['worker']['user']
    statements.append('GRANT EXECUTE ON FUNCTION retail.api_accept_portal_publication_v2(uuid,text),'
                      f'retail.api_portal_publication_state_v2(uuid) TO {legacy_worker_login};')
    if forms:
        statements.append('GRANT EXECUTE ON FUNCTION retail.api_owner_decide_portal_request_v3'
            f"(text,text,uuid,uuid,text,text,text,text) TO {config['reviewer']['user']};")
    if reads:
        login, password = 'raa_wp4_portal_test_' + uuid4().hex[:12], secrets.token_hex(32)
        retain(password)
        config['reader'] = dict(config['worker'], user=login, password=password)
        statements.append(f"CREATE ROLE {login} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS "
            f"CONNECTION LIMIT 4 PASSWORD '{password}'; GRANT CONNECT ON DATABASE {database} TO {login}; "
            f"GRANT USAGE ON SCHEMA retail TO {login}; ALTER ROLE {login} IN DATABASE {database} "
            f"SET default_transaction_read_only=on; ALTER ROLE {login} IN DATABASE {database} "
            f"SET statement_timeout='5s'; GRANT EXECUTE ON FUNCTION retail.api_portal_identity_v1(text),"
            "retail.api_owner_portal_request_v3(text,uuid),retail.api_owner_portal_receipt_v2(text,uuid),"
            f"retail.api_owner_portal_export_v2(text,uuid) TO {login};")
        if forms:
            statements.append('GRANT EXECUTE ON FUNCTION retail.api_owner_portal_review_v3(text,uuid,uuid),'
                              f'retail.api_owner_portal_requests_v3(text) TO {login};')
        if transition:
            statements.append(f'GRANT EXECUTE ON FUNCTION retail.api_owner_portal_transition_v1(text,uuid) TO {login};')
        if transition_api:
            statements.append(f'GRANT EXECUTE ON FUNCTION retail.api_owner_retired_legacy_request_v1(text,uuid,uuid) TO {login};')
    if transition:
        for kind, signatures in (
                ('transition', 'retail.api_transition_legacy_portal_v1(uuid,uuid,text,text,text)'),
                ('legacy', 'retail.api_issue_approval_request_v2(uuid,integer,text,text,uuid),'
                           'retail.api_decide_request_v1(text,text,uuid,uuid,integer,text,text,text,text)')):
            login, password = 'raa_wp4_portal_test_' + uuid4().hex[:12], secrets.token_hex(32)
            retain(password)
            config[kind] = dict(config['worker'], user=login, password=password)
            statements.append(f"CREATE ROLE {login} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS "
                f"CONNECTION LIMIT 4 PASSWORD '{password}'; GRANT CONNECT ON DATABASE {database} TO {login}; "
                f"GRANT USAGE ON SCHEMA retail TO {login}; ALTER ROLE {login} IN DATABASE {database} "
                f"SET default_transaction_read_only=on; ALTER ROLE {login} IN DATABASE {database} "
                f"SET statement_timeout='5s'; GRANT EXECUTE ON FUNCTION {signatures} TO {login};")
        if transition_api:
            statements.append('GRANT EXECUTE ON FUNCTION retail.api_portal_transition_state_v1(uuid,text) '
                              f"TO {config['transition']['user']};")
    if auth:
        login, password = 'raa_wp4_portal_test_' + uuid4().hex[:12], secrets.token_hex(32)
        retain(password)
        config['auth'] = dict(config['worker'], user=login, password=password)
        statements.append(f"CREATE ROLE {login} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS "
            f"CONNECTION LIMIT 4 PASSWORD '{password}'; GRANT CONNECT ON DATABASE {database} TO {login}; "
            f"GRANT USAGE ON SCHEMA retail TO {login}; ALTER ROLE {login} IN DATABASE {database} "
            f"SET default_transaction_read_only=on; ALTER ROLE {login} IN DATABASE {database} "
            f"SET statement_timeout='5s'; GRANT EXECUTE ON FUNCTION retail.api_portal_auth_identity_v2(text),"
            f"retail.api_portal_auth_login_v2(text,text,text,text),retail.api_portal_auth_logout_v2(text,text) TO {login};")
    if worker:
        login,password='raa_wp4_portal_test_'+uuid4().hex[:12],secrets.token_hex(32)
        retain(password)
        config['portal_worker']=dict(config['worker'],user=login,password=password)
        config['worker_token']=secrets.token_hex(32); retain(config['worker_token'])
        statements.append(f"CREATE ROLE {login} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS "
            f"CONNECTION LIMIT 4 PASSWORD '{password}'; GRANT CONNECT ON DATABASE {database} TO {login}; "
            f"GRANT USAGE ON SCHEMA retail TO {login}; ALTER ROLE {login} IN DATABASE {database} "
            f"SET default_transaction_read_only=on; ALTER ROLE {login} IN DATABASE {database} "
            f"SET statement_timeout='5s'; GRANT EXECUTE ON FUNCTION retail.api_worker_portal_state_v2(uuid,text),"
            f"retail.api_worker_accept_portal_v2(uuid,text,uuid,text,text) TO {login};")
    if attempts:
        for kind, signatures in (
                ('attempt_worker', 'retail.api_portal_attempt_state_v1(uuid,text),'
                 'retail.api_reserve_portal_attempt_v1(uuid,text,uuid,text,text,text,text),'
                 'retail.api_accept_portal_attempt_v1(uuid,text,uuid,text),'
                 'retail.api_report_portal_attempt_v1(uuid,text,uuid,text,text),'
                 'retail.api_reconcile_portal_attempt_v1(uuid,text)'),
                ('recovery', 'retail.api_operator_reconcile_portal_v1(uuid,text,text)')):
            login, password = 'raa_wp4_portal_test_' + uuid4().hex[:12], secrets.token_hex(32)
            retain(password)
            config[kind] = dict(config['worker'], user=login, password=password)
            statements.append(f"CREATE ROLE {login} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS "
                f"CONNECTION LIMIT 4 PASSWORD '{password}'; GRANT CONNECT ON DATABASE {database} TO {login}; "
                f"GRANT USAGE ON SCHEMA retail TO {login}; ALTER ROLE {login} IN DATABASE {database} "
                f"SET default_transaction_read_only=on; ALTER ROLE {login} IN DATABASE {database} "
                f"SET statement_timeout='5s'; GRANT EXECUTE ON FUNCTION {signatures} TO {login};")
    if attempt_api:
        for name in ('attempt_token','recovery_token'):
            config[name]=secrets.token_hex(32); retain(config[name])
    docker(['exec', '-i', 'raa-g0-postgres-1', 'psql', '-X', '-q', '-1', '-v',
            'ON_ERROR_STOP=1', '-U', 'g0_user', '-d', database, '-f', '-'], '\n'.join(statements))
    return config


def main(reads=False, forms=False, transition=False, transition_api=False, auth=False, worker=False, attempts=False, attempt_api=False):
    config = provision_portal(reads, forms, transition, transition_api, auth, worker, attempts, attempt_api)
    database = config['database']
    test = ('test_wp4_portal_attempt_api_database.py' if attempt_api else 'test_wp4_portal_attempts_database.py' if attempts else 'test_wp4_portal_worker_database.py' if worker else 'test_wp4_portal_auth_database.py' if auth else 'test_wp4_portal_transition_api_database.py' if transition_api else
            'test_wp4_portal_transition_database.py' if transition else 'test_wp4_portal_review_v3_database.py' if forms else
            'test_wp4_portal_publication_reads_database.py' if reads else 'test_wp4_portal_publication_database.py')
    result = json.loads(docker(['exec', '-i', 'raa-wp2-api', 'python', '-c',
        "import sys,runpy; sys.path.insert(0,'/app/tests'); "
        "runpy.run_path('/app/tests/" + test + "',run_name='__main__')"], json.dumps(config)))
    print('Test database/logins/fixtures retained: ' + database)
    if not result.get('passed'):
        print('FAIL|test-names|' + ','.join(result.get('failed_tests', [])))
        print('FAIL|exception-types|' + ','.join(result.get('error_types', [])))
        print('FAIL|sqlstates|' + ','.join(result.get('sqlstates', [])))
        print('FAIL|constraints|' + ','.join(result.get('constraints', [])))
        raise RuntimeError('Isolated portal foundation failed')
    print('PASS|' + ('portal-attempt-API-real-SQL-ASGI' if attempt_api else 'portal-attempts-real-SQL' if attempts else 'portal-worker-real-SQL-ASGI' if worker else 'portal-auth-real-SQL-ASGI' if auth else 'portal-transition-API-real-SQL-ASGI' if transition_api else
                    'portal-legacy-transition-real-SQL' if transition else 'portal-review-v3-real-SQL-ASGI' if forms else
                    'portal-publication-real-SQL-ASGI' if reads else 'portal-publication-real-SQL') +
          '|' + str(result['tests_run']) + '|no-NTFS|no-runtime-activation')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--reads', action='store_true', help='Isolated commit adapter and owner-only ASGI reads/export')
    mode.add_argument('--forms', action='store_true', help='Isolated service issuance and confirmed owner new-target forms')
    mode.add_argument('--transition', action='store_true', help='Isolated one-way expired-unreviewed legacy transition, no live operation')
    mode.add_argument('--transition-api', action='store_true', help='Isolated service transition/reconciliation and owner history, no deployment')
    mode.add_argument('--auth', action='store_true', help='Isolated native login/logout/session lifecycle, no deployment')
    mode.add_argument('--worker', action='store_true', help='Isolated fixed worker state/acceptance, no main activation')
    mode.add_argument('--attempts', action='store_true', help='Isolated durable attempts/reconciliation/recovery SQL foundation, no runtime activation')
    mode.add_argument('--attempt-api', action='store_true', help='Isolated commit-safe worker/recovery ASGI surfaces, no main/n8n activation')
    args = parser.parse_args()
    try:
        main(args.reads, args.forms, args.transition, args.transition_api, args.auth, args.worker, args.attempts, args.attempt_api)
    except Exception:
        raise SystemExit('FAIL|portal-foundation|details-suppressed-to-protect-secrets') from None
