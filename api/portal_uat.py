"""Closed synthetic-UAT assembly. No main configuration or restored-writer admission."""
import re
from uuid import UUID

import psycopg
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from api.portal import HEX, UAT_BOUNDARY
from api.portal_auth_v2 import IsolatedPortalAuth, install_isolated_auth_v2
from api.portal_publication import IsolatedPortalPublicationStore
from api.portal_attempts import IsolatedAttemptWorker, install_isolated_attempt_worker

SIGNATURES = {
    'reader': (
        'api_portal_identity_v1(text)', 'api_owner_portal_request_v3(text,uuid)',
        'api_owner_portal_receipt_v2(text,uuid)', 'api_owner_portal_export_v2(text,uuid)',
        'api_owner_portal_review_v3(text,uuid,uuid)', 'api_owner_portal_requests_v3(text)',
        'api_owner_portal_transition_v1(text,uuid)', 'api_owner_retired_legacy_request_v1(text,uuid,uuid)',
    ),
    'reviewer': ('api_decide_portal_request_v2(text,text,uuid,text,text,text)',
                 'api_owner_decide_portal_request_v3(text,text,uuid,uuid,text,text,text,text)'),
    'issuer': ('api_issue_portal_request_v3(uuid,text,text,uuid)',),
    'transition': ('api_transition_legacy_portal_v1(uuid,uuid,text,text,text)',
                   'api_portal_transition_state_v1(uuid,text)'),
    'auth': ('api_portal_auth_identity_v2(text)', 'api_portal_auth_login_v2(text,text,text,text)',
             'api_portal_auth_logout_v2(text,text)'),
    'attempt_worker': ('api_portal_attempt_state_v1(uuid,text)',
        'api_reserve_portal_attempt_v1(uuid,text,uuid,text,text,text,text)',
        'api_accept_portal_attempt_v1(uuid,text,uuid,text)',
        'api_report_portal_attempt_v1(uuid,text,uuid,text,text)', 'api_reconcile_portal_attempt_v1(uuid,text)'),
}
OWNER_KINDS = ('reader', 'reviewer', 'issuer', 'transition', 'auth')


class UATOwner(IsolatedPortalAuth):
    def session_html(self, csrf):
        return ('<p>Synthetic UAT only. Historical report fixtures, not the real M02 case. '
                'Publication worker is not admitted by viewing or approving this page.</p>' + super().session_html(csrf))


def require(value):
    if not value:
        raise ValueError('Synthetic UAT admission denied')


def validate_config(config, mode):
    require(mode in ('owner', 'worker') and isinstance(config, dict))
    expected = {'database', 'stores', 'portal_key', 'service_token'} if mode == 'owner' else {
        'database', 'stores', 'worker_token', 'allowed_actions'}
    require(set(config) == expected)
    database = config['database']
    require(isinstance(database, str) and re.fullmatch(r'raa_wp4_dispatch_test_[a-f0-9]{12}', database))
    kinds = OWNER_KINDS if mode == 'owner' else ('attempt_worker',)
    require(isinstance(config['stores'], dict) and set(config['stores']) == set(kinds))
    logins, secrets = [], []
    for kind in kinds:
        db = config['stores'][kind]
        require(isinstance(db, dict) and set(db) == {'host', 'dbname', 'user', 'password'})
        require(db['host'] == 'raa-g0-postgres-1' and db['dbname'] == database)
        require(isinstance(db['user'], str) and re.fullmatch(r'raa_wp4_portal_test_[a-f0-9]{12}', db['user']))
        require(isinstance(db['password'], str) and HEX.fullmatch(db['password']))
        logins.append(db['user']); secrets.append(db['password'])
    for key in ('portal_key', 'service_token') if mode == 'owner' else ('worker_token',):
        require(isinstance(config[key], str) and HEX.fullmatch(config[key]))
        secrets.append(config[key])
    require(len(set(logins)) == len(logins) and len(set(secrets)) == len(secrets))
    if mode == 'worker':
        actions = config['allowed_actions']
        require(isinstance(actions, list) and len(actions) <= 20 and len(set(actions)) == len(actions))
        require(all(isinstance(a, str) and str(UUID(a)) == a for a in actions))
    return kinds


def admit_connection(connection, database, login, kind):
    """Fail before sockets: effective rights, not just counts or direct ACLs.

    This is bounded fresh synthetic-UAT admission, not a function-body integrity,
    restored transaction-ID, cross-cluster single-writer or real-data gate.
    """
    require(connection.autocommit is False)
    require(connection.execute('SELECT current_database(),current_user').fetchone() == (database, login))
    require(connection.execute('SHOW default_transaction_read_only').fetchone() == ('on',))
    require(connection.execute('SHOW statement_timeout').fetchone() == ('5s',))
    require(connection.execute('SHOW lock_timeout').fetchone() == ('1s',))
    flags = connection.execute('SELECT rolcanlogin,rolsuper,rolcreatedb,rolcreaterole,rolreplication,rolbypassrls '
                               'FROM pg_roles WHERE rolname=current_user').fetchone()
    require(flags == (True, False, False, False, False, False))
    require(connection.execute('SELECT count(*) FROM pg_auth_members WHERE member='
        '(SELECT oid FROM pg_roles WHERE rolname=current_user) OR roleid='
        '(SELECT oid FROM pg_roles WHERE rolname=current_user)').fetchone() == (0,))
    require(connection.execute("SELECT has_database_privilege(current_user,current_database(),'CREATE,TEMP')").fetchone() == (False,))
    require(connection.execute("SELECT count(*) FROM pg_namespace WHERE nspname IN ('retail','public') "
                               "AND has_schema_privilege(current_user,oid,'CREATE')").fetchone() == (0,))
    rights = connection.execute("SELECT p.proname||'('||oidvectortypes(p.proargtypes)||')' "
        "FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='retail' "
        "AND has_function_privilege(current_user,p.oid,'EXECUTE') ORDER BY 1").fetchall()
    require({value[0].replace(' ', '') for value in rights} == set(SIGNATURES[kind]))
    require(connection.execute("SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
        "WHERE n.nspname='retail' AND c.relkind IN ('r','p','v','m','f','S') AND ("
        "CASE WHEN c.relkind='S' THEN has_sequence_privilege(current_user,c.oid,'USAGE,SELECT,UPDATE') "
        "ELSE has_table_privilege(current_user,c.oid,'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER') "
        "OR has_any_column_privilege(current_user,c.oid,'SELECT,INSERT,UPDATE,REFERENCES') END)").fetchone() == (0,))
    # Version rows require table access which these applications must never gain.
    # The scoped launcher checks the actual migration inventory before startup.
    require(connection.execute("SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
        "WHERE n.nspname='retail' AND c.relname IN ('portal_approval_requests_v3',"
        "'portal_review_decisions_v2','portal_publications_v2','portal_worker_events_v1') AND c.relkind='r'").fetchone() == (4,))
    connection.rollback()


class SyntheticBoundary:
    """Label every response; worker allowlist is fixed configuration, never a route grant."""
    def __init__(self, app, actions=None):
        self.app, self.actions = app, None if actions is None else frozenset(actions)

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        async def labelled(message):
            if message['type'] == 'http.response.start':
                message = dict(message, headers=[(k,v) for k,v in message.get('headers', []) if k.lower()!=b'x-validation-scope'] +
                               [(b'x-validation-scope', b'synthetic-isolated-uat')])
            await send(message)
        if self.actions is not None:
            match = re.fullmatch(r'/api/v4/portal-actions/([a-f0-9-]{36})(?:/(reserve|accept|report|reconcile))?', scope['path'])
            if not match or match[1] not in self.actions:
                return await JSONResponse({'detail': 'Synthetic allowlisted action required'}, 404)(scope, receive, labelled)
        return await self.app(scope, receive, labelled)


def build_app(config, mode, connector=psycopg.connect):
    kinds = validate_config(config, mode)
    stores = {}
    for kind in kinds:
        db = dict(config['stores'][kind])
        factory = lambda db=db: connector(**db, connect_timeout=5, autocommit=False)
        # A startup failure never binds a listening socket. No elevated credential.
        with factory() as conn:
            admit_connection(conn, config['database'], db['user'], kind)
        stores[kind] = IsolatedPortalPublicationStore(factory, config['database'], db['user'])
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    if mode == 'owner':
        owner = UATOwner(*(stores[k] for k in OWNER_KINDS))
        install_isolated_auth_v2(app, owner, config['portal_key'], config['service_token'], boundary=UAT_BOUNDARY)
        app.add_middleware(SyntheticBoundary)
    else:
        install_isolated_attempt_worker(app, IsolatedAttemptWorker(stores['attempt_worker']), config['worker_token'])
        # Authentication wraps even the allowlist denial; do not leak case existence.
        from api.main import GuardMiddleware
        app.add_middleware(SyntheticBoundary, actions=config['allowed_actions'])
        app.add_middleware(GuardMiddleware, token=config['worker_token'])
        app.add_middleware(SyntheticBoundary)
    return app
