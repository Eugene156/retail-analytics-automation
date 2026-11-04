import asyncio
from hashlib import sha256
import json
import re
import unittest
from urllib.parse import urlencode
from uuid import UUID
from unittest.mock import patch
from fastapi import HTTPException
from api.main import Settings, create_app
from api.portal import CHALLENGE, SESSION, ORIGIN, PortalStore, session_csrf

OWNER = 'a'*64
IDENTITY = UUID('00000000-0000-0000-0000-000000000001')


def call(app, path='/portal/login', method='GET', body=b'', headers=None, chunks=None, query=b''):
    messages, received = [], iter(chunks or [body])
    parts = list(received)
    async def receive():
        if parts:
            return {'type':'http.request','body':parts.pop(0),'more_body':bool(parts)}
        return {'type':'http.disconnect'}
    async def send(value):
        messages.append(value)
    scope = {'type':'http','asgi':{'version':'3.0'},'http_version':'1.1','scheme':'http',
        'method':method,'path':path,'raw_path':path.encode(),'query_string':query,
        'headers':headers if headers is not None else [(b'host',b'127.0.0.1:18081')],
        'server':('127.0.0.1',18081),'client':('127.0.0.1',1),'root_path':''}
    asyncio.run(app(scope,receive,send))
    start=next(x for x in messages if x['type']=='http.response.start')
    return start['status'],b''.join(x.get('body',b'') for x in messages),start['headers']


class Store:
    def __init__(self):
        self.sessions={}
        self.writes=0
    def identity(self, key):
        if key not in self.sessions:
            raise HTTPException(401,'Unauthorized')
        return IDENTITY
    def login(self, owner, session, csrf, old):
        if owner!=sha256(OWNER.encode()).hexdigest():
            raise HTTPException(401,'Unauthorized')
        self.sessions.pop(old,None)
        self.sessions[session]=csrf
        self.writes+=1
        return IDENTITY
    def logout(self, session, csrf):
        if self.sessions.get(session)!=csrf:
            raise HTTPException(401,'Unauthorized')
        del self.sessions[session]
        self.writes+=1
    def requests(self, session):
        self.identity(session)
        return '[]'


class PortalTests(unittest.TestCase):
    def setUp(self):
        self.store=Store()
        self.app=create_app(Settings('b'*64,'unused',portal_login_key='c'*64),portal_store=self.store)
        status, body, headers=call(self.app)
        self.assertEqual(status,200)
        self.assertEqual(dict(headers)[b'referrer-policy'],b'same-origin')
        self.csrf=re.search(rb'name="csrf" value="([a-f0-9]{64})"',body)[1].decode()
        self.challenge=next(v.decode().split(';')[0] for k,v in headers if k==b'set-cookie')

    def post(self, path='/portal/login', token=OWNER, csrf=None, cookie=None, origin=ORIGIN, extra=None, body=None, chunks=None):
        headers=[(b'host',b'127.0.0.1:18081'),(b'content-type',b'application/x-www-form-urlencoded'),
                 (b'cookie',(cookie or self.challenge).encode())]
        if origin is not None:
            headers.append((b'origin',origin.encode()))
        headers.extend(extra or [])
        fields={'csrf':csrf or self.csrf}
        if path=='/portal/login':
            fields['owner_token']=token
        return call(self.app,path,'POST',urlencode(fields).encode() if body is None else body,headers,chunks)

    def login(self):
        status, body, headers=self.post()
        self.assertEqual(status,303)
        return next(v.decode().split(';')[0] for k,v in headers if k==b'set-cookie' and v.startswith(SESSION.encode()+b'='))

    def test_no_service_bearer_or_url_credentials(self):
        for headers,query in (([(b'host',b'localhost:18081')],b''),
            ([(b'host',b'127.0.0.1:18081'),(b'authorization',b'Bearer '+OWNER.encode())],b''),
            (None,b'token='+OWNER.encode()),
            ([(b'host',b'127.0.0.1:18081'),(b'host',b'127.0.0.1:18081')],b'')):
            self.assertEqual(call(self.app,headers=headers,query=query)[0],400)

    def test_origin_and_login_csrf(self):
        for origin in (None,'null','http://evil.invalid','http://127.0.0.1:18082'):
            self.assertEqual(self.post(origin=origin)[0],403)
        self.assertEqual(self.post(extra=[(b'origin',ORIGIN.encode())])[0],403)
        self.assertEqual(self.post(csrf='0'*64)[0],403)
        forged=self.challenge[:-1]+('a' if self.challenge[-1]!='a' else 'b')
        self.assertEqual(self.post(cookie=forged)[0],403)
        self.assertEqual(self.store.writes,0)

    def test_native_form_referrer_policy_does_not_allow_null_origin(self):
        # The old no-referrer header caused navigate-mode form POSTs to send
        # Origin:null. Do not fix compatibility by accepting opaque origins.
        status,_,headers=self.post(origin='null')
        self.assertEqual(status,403)
        self.assertEqual(dict(headers)[b'referrer-policy'],b'same-origin')
        cookie=self.login()
        headers=[(b'host',b'127.0.0.1:18081'),(b'cookie',cookie.encode())]
        status,_,response_headers=call(self.app,'/portal',headers=headers)
        self.assertEqual(status,200)
        self.assertEqual(dict(response_headers)[b'referrer-policy'],b'same-origin')
        self.assertEqual(self.post('/portal/logout',cookie=cookie,
            csrf=session_csrf(cookie.split('=')[1]),origin='null')[0],403)
        self.assertEqual(len(self.store.sessions),1)

    def test_login_challenge_expiry(self):
        issued=int(self.challenge.split('.')[1])
        with patch('api.portal.time.time',return_value=issued+300):
            self.assertEqual(self.post()[0],403)
        with patch('api.portal.time.time',return_value=issued-1):
            self.assertEqual(self.post()[0],403)

    def test_bad_form_duplicate_chunked_bound(self):
        for body in (b'csrf='+self.csrf.encode()+b'&csrf='+self.csrf.encode(),b'csrf=%zz',b'csrf=%ff',b'csrf=x&extra=y',b'bad'):
            self.assertEqual(self.post(body=body)[0],400)
        self.assertEqual(self.post(body=b'x'*2049)[0],413)
        self.assertEqual(self.post(chunks=[b'x'*1024,b'x'*1025])[0],413)
        self.assertEqual(self.post(extra=[(b'cookie',self.challenge.encode())])[0],400)
        self.assertEqual(self.store.writes,0)

    def test_wrong_owner_not_reflected(self):
        for token in ('wrong','0'*64,'b'*64):
            status,body,_=self.post(token=token)
            self.assertEqual(status,401)
            self.assertNotIn(token.encode(),body)
        self.assertEqual(self.store.writes,0)

    def test_cookie_flags_private_headers_no_raw_session_in_page(self):
        cookie=self.login()
        status,body,headers=call(self.app,'/portal',headers=[(b'host',b'127.0.0.1:18081'),(b'cookie',cookie.encode())])
        self.assertEqual(status,200)
        self.assertNotIn(cookie.split('=')[1].encode(),body)
        self.assertEqual(dict(headers)[b'cache-control'],b'no-store')
        self.assertIn(b"frame-ancestors 'none'",dict(headers)[b'content-security-policy'])
        status,_,headers=self.post()
        value=next(v for k,v in headers if k==b'set-cookie' and v.startswith(SESSION.encode()+b'='))
        for part in (b'HttpOnly',b'SameSite=strict',b'Path=/portal',b'Max-Age=3600'):
            self.assertIn(part,value)
        self.assertNotIn(b'Secure',value)  # Explicit loopback HTTP validation limitation.

    def test_rotation_logout_read_only(self):
        cookie=self.login()
        raw=cookie.split('=')[1]
        self.assertEqual(self.post('/portal/logout',csrf='0'*64,cookie=cookie)[0],403)
        self.assertEqual(self.post('/portal/cases/00000000-0000-0000-0000-000000000001/requests/00000000-0000-0000-0000-000000000001',cookie=cookie)[0],405)
        self.assertEqual(self.post('/portal/logout',csrf=session_csrf(raw),cookie=cookie)[0],303)
        self.assertEqual(call(self.app,'/portal',headers=[(b'host',b'127.0.0.1:18081'),(b'cookie',cookie.encode())])[0],303)
        self.assertEqual(self.post('/portal/logout',csrf=session_csrf(raw),cookie=cookie)[0],401)
        cookie=self.login()
        self.assertEqual(self.post(cookie=self.challenge+'; '+cookie)[0],303)
        self.assertNotIn(sha256(cookie.split('=')[1].encode()).hexdigest(),self.store.sessions)

    def test_cookie_does_not_authorize_api_or_bearer_review(self):
        cookie=self.login()
        for path in ('/api/v1/cases/00000000-0000-0000-0000-000000000001','/review/v1/identity'):
            self.assertEqual(call(self.app,path,headers=[(b'host',b'127.0.0.1:18081'),(b'cookie',cookie.encode())])[0],401)

    def test_disabled_configuration_and_openapi(self):
        disabled=create_app(Settings('b'*64,'unused'))
        self.assertEqual(call(disabled)[0],503)
        self.assertFalse(any(p.startswith('/portal') for p in self.app.openapi()['paths']))

    def test_store_admission_does_not_open_connection(self):
        store=PortalStore('unused')
        store.slot.acquire()
        with patch('api.portal.psycopg.connect') as connect:
            with self.assertRaises(HTTPException) as caught:
                store.identity('a'*64)
            self.assertEqual(caught.exception.status_code,429)
            connect.assert_not_called()

    def test_exact_canonical_hash_identity_and_escaped_untrusted_text(self):
        cookie=self.login()
        case='00000000-0000-0000-0000-000000000002'
        proposal_id='00000000-0000-0000-0000-000000000003'
        payload={'case_id':case,'proposal_id':proposal_id,'reviewer_id':str(IDENTITY),
                 'description':'</pre><script>untrusted</script>'}
        canonical=json.dumps(payload)
        value={'proposal':payload,'canonical_payload_text':canonical,'proposal_sha256':sha256(canonical.encode()).hexdigest(),
               'decision_enabled':False,'approved':False,'published':False,'review_status':'expired'}
        self.store.proposal=lambda *args:json.dumps(value)
        path='/portal/cases/'+case+'/requests/'+proposal_id
        headers=[(b'host',b'127.0.0.1:18081'),(b'cookie',cookie.encode())]
        status,body,_=call(self.app,path,headers=headers)
        self.assertEqual(status,200)
        self.assertNotIn(b'<script>',body)
        self.assertIn(b'&lt;script&gt;',body)
        self.assertIn(b'Status: expired',body)
        value['proposal_sha256']='0'*64
        self.assertEqual(call(self.app,path,headers=headers)[0],409)
        value['proposal_sha256']=sha256(canonical.encode()).hexdigest()
        value['approved']=True
        self.assertEqual(call(self.app,path,headers=headers)[0],409)
