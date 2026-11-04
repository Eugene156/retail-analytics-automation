"""Closed profiles/cookies/config/effective-privilege gate; mock-only admission."""
from dataclasses import FrozenInstanceError
import re
import unittest
from urllib.parse import urlencode

from fastapi import FastAPI
from api.portal import PortalBoundary, PortalGuard, LEGACY_BOUNDARY, UAT_BOUNDARY, _install_auth_routes, html, page
from api import portal_uat as uat
from test_wp4_portal import call, Store, OWNER


def config(mode='owner'):
    kinds=uat.OWNER_KINDS if mode=='owner' else ('attempt_worker',)
    stores={k:dict(host='raa-g0-postgres-1',dbname='raa_wp4_dispatch_test_'+'a'*12,
                   user='raa_wp4_portal_test_'+format(n,'012x'),password=format(n,'064x'))
            for n,k in enumerate(kinds,1)}
    value=dict(database='raa_wp4_dispatch_test_'+'a'*12,stores=stores)
    value.update(dict(portal_key='b'*64,service_token='c'*64) if mode=='owner' else
                 dict(worker_token='d'*64,allowed_actions=[]))
    return value


class Connection:
    autocommit=False
    def __init__(self,kind='reader',alter=None):self.kind,self.alter,self.last=kind,alter,None
    def execute(self,query):self.last=query;return self
    def fetchone(self):
        q=self.last
        if self.alter and self.alter[0] in q:return self.alter[1]
        if q.startswith('SELECT current_database'):return (config()['database'],config()['stores'][self.kind]['user'])
        if 'default_transaction_read_only' in q:return ('on',)
        if 'statement_timeout' in q:return ('5s',)
        if 'lock_timeout' in q:return ('1s',)
        if 'rolcanlogin' in q:return (True,False,False,False,False,False)
        if 'has_database_privilege' in q:return (False,)
        if "c.relname IN" in q:return (4,)
        return (0,)
    def fetchall(self):
        if self.alter and self.alter[0] in self.last:return self.alter[1]
        return [(s,) for s in uat.SIGNATURES[self.kind]]
    def rollback(self):pass


class UATTests(unittest.TestCase):
    def test_profiles_are_closed_and_frozen(self):
        self.assertEqual(LEGACY_BOUNDARY.origin,'http://127.0.0.1:18081')
        self.assertNotEqual(LEGACY_BOUNDARY.session,UAT_BOUNDARY.session)
        self.assertNotEqual(LEGACY_BOUNDARY.challenge,UAT_BOUNDARY.challenge)
        for p in ('http://evil','localhost','http://127.0.0.1:9999'):
            with self.assertRaises(ValueError):PortalBoundary(p)
        with self.assertRaises(FrozenInstanceError):UAT_BOUNDARY.profile='legacy'

    def app(self):
        store=Store();app=FastAPI()
        app.add_middleware(PortalGuard,store=store,key='c'*64,boundary=UAT_BOUNDARY)
        _install_auth_routes(app,store,'c'*64,lambda t,c:html(page(t,c)),UAT_BOUNDARY)
        return app,store

    def test_uat_host_and_origin_do_not_admit_legacy_or_wildcard(self):
        app,_=self.app()
        for host in ('127.0.0.1:18081','localhost:18082','0.0.0.0:18082'):
            self.assertEqual(call(app,headers=[(b'host',host.encode())])[0],400)
        self.assertEqual(call(app,headers=[(b'host',UAT_BOUNDARY.host.encode()),
                           (b'origin',LEGACY_BOUNDARY.origin.encode())])[0],403)

    def test_uat_cookie_namespace_login_logout_and_legacy_cookie_denial(self):
        app,store=self.app();host=[(b'host',UAT_BOUNDARY.host.encode())]
        status,body,headers=call(app,headers=host);self.assertEqual(status,200)
        nonce=re.search(rb'name="csrf" value="([a-f0-9]{64})"',body)[1].decode()
        challenge=next(v.decode().split(';')[0] for k,v in headers if k==b'set-cookie')
        self.assertTrue(challenge.startswith(UAT_BOUNDARY.challenge+'='))
        body=urlencode(dict(owner_token=OWNER,csrf=nonce)).encode()
        common=host+[(b'origin',UAT_BOUNDARY.origin.encode()),(b'content-type',b'application/x-www-form-urlencoded')]
        status,_,headers=call(app,method='POST',body=body,headers=common+[(b'cookie',challenge.encode())])
        self.assertEqual(status,303)
        session=next(v.decode().split(';')[0] for k,v in headers if k==b'set-cookie' and v.startswith(UAT_BOUNDARY.session.encode()+b'='))
        raw=session.split('=',1)[1]
        self.assertEqual(call(app,'/portal',headers=host+[(b'cookie',(LEGACY_BOUNDARY.session+'='+raw).encode())])[0],303)
        from api.portal import session_csrf
        status,_,headers=call(app,'/portal/logout','POST',urlencode(dict(csrf=session_csrf(raw))).encode(),common+[(b'cookie',session.encode())])
        self.assertEqual(status,303);self.assertEqual(store.sessions,{})
        self.assertTrue(any(UAT_BOUNDARY.session.encode()+b'=' in v for k,v in headers if k==b'set-cookie'))

    def test_owner_and_worker_exact_configs_pass(self):
        self.assertEqual(uat.validate_config(config(),'owner'),uat.OWNER_KINDS)
        self.assertEqual(uat.validate_config(config('worker'),'worker'),('attempt_worker',))

    def test_admin_main_other_host_duplicate_identity_or_secret_denied(self):
        for mutate in (lambda c:c.update(admin={}),lambda c:c.update(database='raa_wp2_validation'),
                       lambda c:c['stores']['reader'].update(host='external.example'),
                       lambda c:c['stores']['reader'].update(user='g0_user'),
                       lambda c:c['stores']['auth'].update(user=c['stores']['reader']['user']),
                       lambda c:c.update(service_token=c['portal_key'])):
            c=config();mutate(c)
            with self.assertRaises(ValueError):uat.validate_config(c,'owner')

    def test_worker_cannot_hold_owner_operator_or_arbitrary_action(self):
        for mutate in (lambda c:c['stores'].update(auth=config()['stores']['auth']),
                       lambda c:c.update(recovery_token='f'*64),lambda c:c.update(allowed_actions=['not-an-id'])):
            c=config('worker');mutate(c)
            with self.assertRaises(ValueError):uat.validate_config(c,'worker')

    def test_exact_effective_rights_pass(self):
        c=config()
        for k in uat.OWNER_KINDS:
            uat.admit_connection(Connection(k),c['database'],c['stores'][k]['user'],k)

    def test_missing_extra_table_membership_or_privileged_rights_deny(self):
        changes=(('rolcanlogin',(True,True,False,False,False,False)),('pg_auth_members',(1,)),
                 ('has_database_privilege',(True,)),('has_schema_privilege',(1,)),
                 ('has_table_privilege',(1,)),('c.relname IN',(3,)),
                 ('has_function_privilege',[('api_accept_portal_publication_v2(uuid,text)',)]))
        c=config()
        for change in changes:
            with self.assertRaises(ValueError):uat.admit_connection(Connection(alter=change),c['database'],c['stores']['reader']['user'],'reader')

    def test_autocommit_identity_or_unbounded_timeout_denied(self):
        c=config()
        for change in (('current_database',('n8n','g0_user')),('default_transaction_read_only',('off',)),
                       ('statement_timeout',('0',)),('lock_timeout',('0',))):
            with self.assertRaises(ValueError):uat.admit_connection(Connection(alter=change),c['database'],c['stores']['reader']['user'],'reader')
        conn=Connection();conn.autocommit=True
        with self.assertRaises(ValueError):uat.admit_connection(conn,c['database'],c['stores']['reader']['user'],'reader')

    def test_config_failure_precedes_any_connection(self):
        c=config();c['database']='n8n';calls=[]
        with self.assertRaises(ValueError):uat.build_app(c,'owner',lambda **kwargs:calls.append(kwargs))
        self.assertEqual(calls,[])

    def test_worker_empty_allowlist_and_auth_deny_before_business_call(self):
        from unittest.mock import patch
        from contextlib import nullcontext
        app=FastAPI();c=config('worker')
        with patch.object(uat,'admit_connection'):
            app=uat.build_app(c,'worker',lambda **kwargs:nullcontext(Connection()))
        path='/api/v4/portal-actions/00000000-0000-0000-0000-000000000001/accept'
        self.assertEqual(call(app,path,'POST',b'{}')[0],401)
        headers=[(b'authorization',('Bearer '+c['worker_token']).encode()),(b'content-type',b'application/json')]
        status,_,response=call(app,path,'POST',b'{}',headers)
        self.assertEqual(status,404)
        self.assertEqual(dict(response)[b'x-validation-scope'],b'synthetic-isolated-uat')
        self.assertFalse(any(route.path.endswith('/recover') for route in app.routes))

    def test_synthetic_header_is_unique_even_nested_boundaries(self):
        app=FastAPI()
        @app.get('/safe')
        def safe():return {'ok':True}
        app.add_middleware(uat.SyntheticBoundary);app.add_middleware(uat.SyntheticBoundary)
        status,_,headers=call(app,'/safe')
        self.assertEqual(status,200)
        self.assertEqual(sum(k==b'x-validation-scope' for k,v in headers),1)


if __name__=='__main__':unittest.main()
