"""Offline safety checks only; no claim of real approval/publication execution."""
import asyncio
import json
import re
import unittest
from urllib.parse import urlencode
from unittest.mock import patch
from fastapi import HTTPException
from api.p12_demo import build_app, local_json, terminal


def config():
    kinds=('reader','reviewer','issuer','transition','auth','registry','state','worker')
    return {'database':'raa_wp4_dispatch_test_123456abcdef','portal_key':'a'*64,'service_token':'b'*64,
        'callback_token':'c'*64,'primary_token':'d'*64,'stores':{
        k:{'host':'postgres','dbname':'raa_wp4_dispatch_test_123456abcdef',
           'user':'raa_wp4_portal_test_'+format(i,'012x'),'password':'e'*64} for i,k in enumerate(kinds,1)}}


async def response(app,path,method,headers,body=b'{}',query=b''):
    messages=[]
    async def receive():return {'type':'http.request','body':body,'more_body':False}
    async def send(message):messages.append(message)
    await app({'type':'http','asgi':{'version':'3.0'},'http_version':'1.1','scheme':'http',
        'method':method,'path':path,'raw_path':path.encode(),'query_string':query,
        'headers':headers,'client':('127.0.0.1',50000),'server':('127.0.0.1',18082)},receive,send)
    start=next(m for m in messages if m['type']=='http.response.start')
    return start['status'],b''.join(m.get('body',b'') for m in messages),start['headers']


async def status(app,path,method,headers):
    return (await response(app,path,method,headers))[0]


class P12SafetyTests(unittest.TestCase):
    def test_exact_login_tracking_redirect_preserves_clean_login(self):
        headers=[(b'host',b'127.0.0.1:18082'),(b'sec-fetch-site',b'cross-site'),
                 (b'sec-fetch-mode',b'navigate'),(b'sec-fetch-dest',b'document')]
        app=build_app(config())
        with patch('api.p12_demo.psycopg.connect') as db:
            code,body,returned=asyncio.run(response(app,'/portal/login','GET',headers,query=b'utm_source=chatgpt.com'))
            self.assertEqual(code,303)
            self.assertEqual(dict(returned)[b'location'],b'/portal/login')
            self.assertEqual(body,b'')
            self.assertNotIn(b'set-cookie',dict(returned))
            self.assertEqual(asyncio.run(response(app,'/portal/login','GET',headers))[0],200)
            db.assert_not_called()

    def test_login_tracking_rejects_variants_methods_and_unsafe_boundaries(self):
        app=build_app(config())
        headers=[(b'host',b'127.0.0.1:18082')]
        queries=(b'utm_source=chatgpt.com&utm_source=chatgpt.com',
            b'utm_source=other&utm_source=chatgpt.com', b'utm_source=chatgpt.com&extra=1',
            b'extra=1&utm_source=chatgpt.com', b'utm_source=other', b'anything=1',
            b'utm_source=chatgpt.com&', b'utm_source=chatgpt%2Ecom', b'%75tm_source=chatgpt.com')
        with patch('api.p12_demo.psycopg.connect') as db:
            for query in queries:
                with self.subTest(query=query):
                    self.assertEqual(asyncio.run(response(app,'/portal/login','GET',headers,query=query))[0],400)
            for path,method in (('/portal/login','POST'),('/portal/login','HEAD'),
                                ('/portal/logout','POST')):
                self.assertEqual(asyncio.run(response(app,path,method,headers,query=b'utm_source=chatgpt.com'))[0],400)
            for hs,expected in (([(b'host',b'localhost:18082')],400),
                               (headers+[(b'origin',b'http://evil.invalid')],403),
                               (headers+[(b'authorization',b'Bearer synthetic')],400),
                               (headers+[(b'sec-fetch-site',b'cross-site')],403),
                               (headers+headers,400)):
                self.assertEqual(asyncio.run(response(app,'/portal/login','GET',hs,query=b'utm_source=chatgpt.com'))[0],expected)
            db.assert_not_called()

    def test_index_tracking_requires_owner_and_preserves_boundary_checks(self):
        from fastapi import FastAPI
        from fastapi.responses import Response
        from api.portal import PortalGuard, UAT_BOUNDARY
        from unittest.mock import Mock
        store=Mock()
        app=FastAPI()
        app.add_middleware(PortalGuard,store=store,key='a'*64,boundary=UAT_BOUNDARY,demo_document_navigation=True)
        @app.get('/portal')
        def index():return Response('synthetic protected index')
        headers=[(b'host',b'127.0.0.1:18082')]
        query=b'utm_source=chatgpt.com'
        code,body,returned=asyncio.run(response(app,'/portal','GET',headers,query=query))
        self.assertEqual(code,303);self.assertEqual(dict(returned)[b'location'],b'/portal/login')
        store.identity.assert_not_called()
        authorized=headers+[(b'cookie',(UAT_BOUNDARY.session+'='+'f'*64).encode())]
        code,body,returned=asyncio.run(response(app,'/portal','GET',authorized,query=query))
        self.assertEqual(code,303);self.assertEqual(dict(returned)[b'location'],b'/portal')
        self.assertEqual(body,b'');self.assertNotIn(b'set-cookie',dict(returned))
        store.identity.assert_called_once()
        self.assertEqual(asyncio.run(response(app,'/portal','GET',authorized))[1],b'synthetic protected index')
        store.identity.reset_mock()
        for variant in (query+b'&utm_source=chatgpt.com',query+b'&extra=1',b'extra=1',b'utm_source=other',query+b'&',b'utm_source=chatgpt%2Ecom'):
            self.assertEqual(asyncio.run(response(app,'/portal','GET',authorized,query=variant))[0],400)
        for hs,expected in ((authorized+[(b'origin',b'http://evil.invalid')],403),
                            (authorized+[(b'host',b'127.0.0.1:18082')],400),
                            (authorized+[(b'authorization',b'Bearer synthetic')],400),
                            (authorized+[(b'sec-fetch-site',b'cross-site')],403)):
            self.assertEqual(asyncio.run(response(app,'/portal','GET',hs,query=query))[0],expected)
        for method in ('POST','HEAD'):
            self.assertEqual(asyncio.run(response(app,'/portal',method,authorized,query=query))[0],400)
        store.identity.assert_not_called()
        store.identity.side_effect=HTTPException(401,'Unauthorized')
        self.assertEqual(dict(asyncio.run(response(app,'/portal','GET',authorized,query=query))[2])[b'location'],b'/portal/login')

    def test_tracking_login_exception_does_not_apply_to_other_portal_profiles(self):
        from fastapi import FastAPI
        from api.portal import PortalGuard, LEGACY_BOUNDARY, UAT_BOUNDARY
        from test_wp4_portal import call, Store
        for boundary in (LEGACY_BOUNDARY, UAT_BOUNDARY):
            app=FastAPI()
            app.add_middleware(PortalGuard,store=Store(),key='a'*64,boundary=boundary)
            self.assertEqual(call(app,'/portal/login',headers=[(b'host',boundary.host.encode())],
                                  query=b'utm_source=chatgpt.com')[0],400)

    def login_challenge(self, app):
        headers=[(b'host',b'127.0.0.1:18082'),(b'sec-fetch-site',b'cross-site'),
                 (b'sec-fetch-mode',b'navigate'),(b'sec-fetch-dest',b'document')]
        code,body,returned=asyncio.run(response(app,'/portal/login','GET',headers))
        self.assertEqual(code,200)
        cookie=next(v.split(b';')[0] for k,v in returned if k==b'set-cookie')
        csrf=re.search(rb'name="csrf" value="([a-f0-9]{64})"',body)[1].decode()
        return cookie,csrf

    def submit_synthetic_login(self, app, cookie, csrf):
        headers=[(b'host',b'127.0.0.1:18082'),(b'origin',b'http://127.0.0.1:18082'),
                 (b'sec-fetch-site',b'same-origin'),(b'content-type',b'application/x-www-form-urlencoded')]
        if cookie is not None:headers.append((b'cookie',cookie))
        # No real credential or database: the mocked auth store always rejects.
        body=urlencode({'owner_token':'f'*64,'csrf':csrf}).encode()
        return asyncio.run(response(app,'/portal/login','POST',headers,body))[0]

    def test_demo_navigation_challenge_valid_before_five_minute_deadline(self):
        app=build_app(config())
        with patch('api.portal.time.time',return_value=1800000000):
            cookie,csrf=self.login_challenge(app)
        for elapsed,expected in ((299,401),(300,403),(-1,403)):
            with self.subTest(elapsed=elapsed), patch('api.portal.time.time',return_value=1800000000+elapsed), \
                 patch('api.portal_auth_v2.IsolatedPortalAuth.login',side_effect=HTTPException(401,'Unauthorized')) as login, \
                 patch('api.p12_demo.psycopg.connect') as db:
                self.assertEqual(self.submit_synthetic_login(app,cookie,csrf),expected)
                self.assertEqual(login.call_count,1 if elapsed==299 else 0)
                db.assert_not_called()

    def test_missing_cookie_and_stale_tab_fail_before_owner_authentication(self):
        app=build_app(config())
        with patch('api.portal.time.time',return_value=1800000000):
            old_cookie,old_csrf=self.login_challenge(app)
            new_cookie,new_csrf=self.login_challenge(app)
            self.assertNotEqual(old_csrf,new_csrf)
            for cookie,csrf in ((None,old_csrf),(new_cookie,old_csrf)):
                with patch('api.portal_auth_v2.IsolatedPortalAuth.login') as login, \
                     patch('api.p12_demo.psycopg.connect') as db:
                    self.assertEqual(self.submit_synthetic_login(app,cookie,csrf),403)
                    login.assert_not_called();db.assert_not_called()

    def test_document_navigation_opens_login_without_database_access(self):
        for site in (b'none', b'same-origin', b'same-site', b'cross-site'):
            with self.subTest(site=site), patch('api.p12_demo.psycopg.connect') as db:
                headers=[(b'host',b'127.0.0.1:18082'),(b'sec-fetch-site',site),
                         (b'sec-fetch-mode',b'navigate'),(b'sec-fetch-dest',b'document'),
                         (b'referer',b'https://external.invalid/')]
                app=build_app(config())
                self.assertEqual(asyncio.run(status(app,'/portal','GET',headers)),303)
                self.assertEqual(asyncio.run(status(app,'/portal/login','GET',headers)),200)
                db.assert_not_called()

    def test_cross_site_navigation_exception_cannot_authorize_other_requests(self):
        base=[(b'host',b'127.0.0.1:18082'),(b'sec-fetch-site',b'cross-site')]
        navigation=[(b'sec-fetch-mode',b'navigate'),(b'sec-fetch-dest',b'document')]
        decision='/portal/cases/'+'1'*36+'/requests/'+'2'*36+'/decision'
        cases=[('/portal','GET',base),
               ('/portal','GET',base+[(b'sec-fetch-mode',b'cors'),(b'sec-fetch-dest',b'empty')]),
               ('/portal','GET',base+[(b'sec-fetch-mode',b'navigate'),(b'sec-fetch-dest',b'iframe')]),
               ('/portal','GET',base+navigation+[(b'origin',b'https://external.invalid')]),
               ('/portal/login','POST',base+navigation),
               (decision,'POST',base+navigation+[(b'origin',b'http://127.0.0.1:18082')])]
        for path,method,headers in cases:
            with self.subTest(path=path,method=method,headers=headers), patch('api.p12_demo.psycopg.connect') as db:
                self.assertEqual(asyncio.run(status(build_app(config()),path,method,headers)),403)
                db.assert_not_called()

    def test_localhost_alias_and_remote_host_remain_rejected(self):
        for host in (b'localhost:18082',b'external.invalid:18082'):
            with self.subTest(host=host), patch('api.p12_demo.psycopg.connect') as db:
                self.assertEqual(asyncio.run(status(build_app(config()),'/portal','GET',[(b'host',host)])),400)
                db.assert_not_called()

    def test_service_cannot_run_without_credential(self):
        with patch('api.p12_demo.psycopg.connect') as db:
            self.assertEqual(asyncio.run(status(build_app(config()),'/api/demo/advance','POST',[])),401)
            db.assert_not_called()

    def test_existing_portal_origin_guard_still_runs_before_database(self):
        with patch('api.p12_demo.psycopg.connect') as db:
            headers=[(b'host',b'127.0.0.1:18082'),(b'origin',b'https://untrusted.invalid')]
            self.assertEqual(asyncio.run(status(build_app(config()),'/portal/login','POST',headers)),403)
            db.assert_not_called()

    def test_external_target_cannot_receive_service_credential(self):
        with patch('api.p12_demo.build_opener') as opener:
            with self.assertRaises(HTTPException):local_json('https://untrusted.invalid',{'Authorization':'Bearer test'})
            opener.assert_not_called()

    def test_uncommitted_or_rejected_decision_cannot_claim_publication(self):
        for decision,publication in ((None,'some-publication'),('rejected','some-publication')):
            with self.assertRaises(HTTPException):terminal(decision,publication)


if __name__=='__main__':unittest.main()
