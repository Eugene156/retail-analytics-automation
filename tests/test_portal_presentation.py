"""Offline presentation preservation; never makes a decision or accesses a DB."""
from html.parser import HTMLParser
import unittest
from api.p12_demo import style_demo_portal
from api.portal_review_v3 import _html
from api.p12_demo import DemoCopy
import asyncio

class Forms(HTMLParser):
    def __init__(self):super().__init__();self.fields=[]
    def handle_starttag(self,tag,attrs):
        if tag in ('form','input','button'):self.fields.append((tag,dict(attrs)))

class PresentationTests(unittest.TestCase):
    def test_actual_request_cards_keep_links_status_generation_and_deadline(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        from api.p12_demo import build_app
        from test_p12_demo import config
        case='11111111-1111-4111-8111-111111111111'
        request='22222222-2222-4222-8222-222222222222'
        row=dict(case_id=case,request_id=request,review_status='rejected',generation=1,expires_at='2026-11-05T03:29:53Z')
        app=build_app(config())
        endpoint=next(route.endpoint for route in app.routes if route.path=='/portal')
        with patch('api.p12_demo.IsolatedPortalAuth.requests',return_value=[row]),patch('api.p12_demo.IsolatedPortalAuth.session_html',return_value='<button>Sign out</button>'):
            result=asyncio.run(endpoint(SimpleNamespace(state=SimpleNamespace(portal_digest='synthetic',portal_csrf='synthetic'))))
        output=style_demo_portal(result.body).decode()
        self.assertIn(f'href="/portal/cases/{case}/requests/{request}"',output)
        self.assertIn('<span>rejected</span>',output)
        self.assertIn('<span class="portal-generation">generation 1</span>',output)
        self.assertIn('Original deadline: '+row['expires_at'],output)
        self.assertIn('.portal-generation{white-space:nowrap}',output)
        self.assertIn('Sign out',output)

    def test_login_and_index_presentation_preserves_forms_links_and_headers(self):
        pages={
            '/portal/login': _html('Owner sign-in','<form action="/portal/login" method="post"><label for="token">Owner token</label><input id="token" name="owner_token" type="password" required minlength="64" maxlength="64" autocomplete="off"><input type="hidden" name="csrf" value="synthetic"><button>Sign in</button></form>',False,auth_page=True),
            '/portal': _html('Portal publication requests','<ul><li><a href="/portal/cases/c/requests/r">Request r</a> · rejected · generation 1<br>Original deadline: exact-deadline</li></ul><form action="/portal/logout" method="post"><input type="hidden" name="csrf" value="synthetic"><button>Sign out</button></form>')}
        async def render(path,original,method='GET'):
            messages=[]
            async def app(scope,receive,send):
                await send({'type':'http.response.start','status':200,'headers':list(original.raw_headers)})
                await send({'type':'http.response.body','body':original.body})
            async def receive():return {'type':'http.request','body':b''}
            async def send(message):messages.append(message)
            await DemoCopy(app)({'method':method,'path':path},receive,send)
            return dict(messages[0]['headers']),messages[1]['body'].decode()
        for path,original in pages.items():
            with self.subTest(path=path):
                headers,output=asyncio.run(render(path,original))
                before,after=Forms(),Forms();before.feed(original.body.decode());after.feed(output)
                self.assertEqual(before.fields,after.fields)
                for key,value in original.raw_headers:
                    if key!=b'content-length':self.assertEqual(headers[key],value)
                self.assertEqual(int(headers[b'content-length']),len(output.encode()))
                self.assertIn('class="sidebar"',output);self.assertIn('class="f2-panel"',output)
                self.assertEqual(output.count('Local portfolio demonstration.'),1)
                self.assertNotIn('<script',output)
                if path=='/portal':
                    self.assertIn('href="/portal/cases/c/requests/r"',output)
                    self.assertIn('rejected · generation 1<br>Original deadline: exact-deadline',output)
                self.assertNotIn('class="sidebar"',asyncio.run(render(path,original,'POST'))[1])
        self.assertNotIn('class="sidebar"',asyncio.run(render('/portal/login/extra',pages['/portal/login']))[1])

    def test_pending_review_keeps_exact_forms_bindings_and_security_headers(self):
        form='<form action="/portal/cases/c/requests/r/decision" method="post"><input name="csrf" value="synthetic"><input type="checkbox" name="confirm" value="yes" required><button name="choice" value="approve">Approve</button><button name="choice" value="reject">Reject</button></form><form action="/portal/logout" method="post"><input name="csrf" value="synthetic"><button>Sign out</button></form>'
        original=_html('Portal publication review',form+'<dl><dt>Report hash</dt><dd>exact-hash</dd><dt>Deadline</dt><dd>exact-deadline</dd></dl>')
        output=style_demo_portal(original.body).decode()
        before,after=Forms(),Forms();before.feed(original.body.decode());after.feed(output)
        self.assertEqual(before.fields,after.fields)
        self.assertIn(form,output);self.assertIn('exact-hash',output);self.assertIn('exact-deadline',output)
        self.assertIn('class="sidebar"',output);self.assertIn('class="f2-panel"',output)
        self.assertEqual(output.count('Local portfolio demonstration.'),1)
        self.assertNotIn('<script',output)
        self.assertIn("style-src 'unsafe-inline'",original.headers['content-security-policy'])
    def test_result_and_saved_history_keep_states_receipts_and_collapsed_payloads(self):
        for state in ('APPROVED','REJECTED','published','rejected'):
            with self.subTest(state=state):
                content='<h2>'+state+'</h2><details><summary>Exact approval contract</summary><pre>exact-contract</pre></details><h2>Publication receipt</h2><pre>exact-receipt</pre>'
                output=style_demo_portal(_html('Human Approval result',content).body).decode()
                self.assertIn(state,output)
                self.assertIn('<details><summary>Exact approval contract</summary><pre>exact-contract</pre></details>',output)
                self.assertIn('<details><summary>Saved payload</summary><pre>exact-receipt</pre></details>',output)
                self.assertNotIn('<details open',output)
