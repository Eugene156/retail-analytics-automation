"""Demo-only assembly of existing owner auth/review and guarded portal publisher.

The browser decision commits before the fixed local n8n webhook is called.
n8n has service credentials only; it cannot approve, impersonate an owner or
choose the publication target. Unknown publication outcomes reconcile by key.
"""
from hashlib import sha256
from html import escape
import json
from pathlib import Path
import re
from urllib.error import HTTPError
from urllib.request import Request as URLRequest, HTTPRedirectHandler, build_opener
from uuid import UUID

import psycopg
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from starlette.concurrency import run_in_threadpool

from api.portal import HEADERS, UAT_BOUNDARY, _install_auth_routes
from api.portal_auth_v2 import IsolatedPortalAuth
from api.portal_publication import IsolatedPortalPublicationStore
from api.portal_review_v3 import _html, install_isolated_review_v3
from api.portal_worker_v2 import IsolatedPortalWorker

CONFIG = Path('/run/p12/config.json')
PRIMARY = 'http://api:8000'
HOOK = 'http://n8n:5678/webhook/p12-decision'


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):
        return None


def local_json(url, headers, body=None):
    """Only fixed callers construct the URL; never accept a supplied URL."""
    try:
        request = URLRequest(url, headers=headers, data=None if body is None else json.dumps(body).encode())
        if not (url.startswith(PRIMARY+'/api/v1/cases/') or url==HOOK):
            raise ValueError()
        with build_opener(NoRedirect).open(request, timeout=35) as response:
            raw = response.read(65537)
            if len(raw)>65536:
                raise ValueError()
            return raw
    except Exception:
        raise HTTPException(503, 'Local workflow outcome unavailable; inspect the stored request before retry') from None


def terminal(decision, publication):
    if decision == 'rejected':
        if publication is not None:
            raise HTTPException(503, 'Rejected publication invariant failed')
        return 'REJECTED'
    if decision == 'approved':
        return 'PUBLISHED' if publication is not None else 'APPROVED'
    raise HTTPException(409, 'A committed human decision is required')


def style_demo_portal(body):
    """Presentation only: reuse mounted F2 assets without changing the portal CSP."""
    assets = Path(__file__).with_name('f2_assets')
    template = (assets/'index.html').read_text(encoding='utf-8')
    sidebar = '<aside' + template.split('<aside', 1)[1].split('</aside>', 1)[0] + '</aside>'
    header = '<header' + template.split('<header', 1)[1].split('</header>', 1)[0] + '</header>'
    css = (Path(__file__).with_name('overview_assets')/'overview.css').read_text(encoding='utf-8')
    css += '\n' + (assets/'f2.css').read_text(encoding='utf-8')
    html = body.decode('utf-8')
    html = re.sub(r'<style>.*?</style>', lambda _: '<style>'+css+'</style>', html, count=1, flags=re.S)
    html = html.replace('<main>', sidebar+'<div class="workspace">'+header+
                        '<main class="portal-page"><section class="f2-panel">', 1)
    html = html.replace('</main>', '</section><p class="evidence-footnote">Local portfolio demonstration.</p></main></div>', 1)
    # Preserve existing contracts/reports in their original disclosures; wrap only bare payloads.
    html = re.sub(r'<details\b[^>]*>.*?</details>|<pre>.*?</pre>',
                  lambda m: m[0] if m[0].startswith('<details') else
                  '<details><summary>Saved payload</summary>'+m[0]+'</details>', html, flags=re.S)
    html = html.replace('Isolated validation · ', '', 1)
    return html.encode('utf-8')


class DemoCopy:
    """Update only fixed presentation notices; preserve the existing guards."""
    def __init__(self, app):
        self.app=app

    async def __call__(self, scope, receive, send):
        start=None; parts=[]; html=False
        async def emit(message):
            nonlocal start,html
            if message['type']=='http.response.start':
                html=any(k.lower()==b'content-type' and v.startswith(b'text/html') for k,v in message['headers'])
                if html:
                    start=message; return
            elif message['type']=='http.response.body' and html:
                parts.append(message.get('body',b''))
                if message.get('more_body',False):return
                body=b''.join(parts).replace(b' \xc2\xb7 automatic publication disabled</p>',b' \xc2\xb7 approved demo publication via n8n</p>')
                body=body.replace(b'Publishing is unavailable.</p>',b'Approved demo reports publish to this local portal.</p>')
                if (scope.get('method') == 'GET' and re.fullmatch(
                        r'/portal(?:/login|(?:/demo)?/cases/[a-f0-9-]{36}/requests/[a-f0-9-]{36})?',
                        scope.get('path', ''))):
                    body=style_demo_portal(body)
                start['headers']=[(k,v) for k,v in start['headers'] if k.lower()!=b'content-length']+[(b'content-length',str(len(body)).encode())]
                await send(start); await send({'type':'http.response.body','body':body}); return
            await send(message)
        await self.app(scope,receive,emit)


def build_app(config):
    database=config['database']
    if not re.fullmatch(r'raa_wp4_dispatch_test_[a-f0-9]{12}',database):
        raise ValueError('Guarded demo approval database required')
    def store(kind):
        db=config['stores'][kind]
        if db['host']!='postgres' or db['dbname']!=database:
            raise ValueError('Demo database binding required')
        return IsolatedPortalPublicationStore(lambda:psycopg.connect(**db,connect_timeout=5),database,db['user'])
    reader,reviewer,issuer,transition,auth=(store(k) for k in ('reader','reviewer','issuer','transition','auth'))
    owner=IsolatedPortalAuth(reader,reviewer,issuer,transition,auth)
    registry,state,worker_store=(store(k) for k in ('registry','state','worker'))
    worker=IsolatedPortalWorker(worker_store)
    app=FastAPI(title='P1.2 local Human Approval demo',docs_url=None,redoc_url=None,openapi_url=None)
    install_isolated_review_v3(app,owner,config['portal_key'],config['service_token'],boundary=UAT_BOUNDARY,
                               demo_document_navigation=True)
    _install_auth_routes(app,owner,config['portal_key'],lambda title,content:_html(title,content,False,auth_page=True),UAT_BOUNDARY)

    @app.get('/healthz')
    def health():return {'status':'ok'}

    def service_only(request):
        if request.scope.get('query_string') or any(k.lower() in (b'cookie',b'origin') for k,v in request.scope['headers']):
            raise HTTPException(400,'Service request required')

    @app.post('/api/demo/register')
    async def register(request:Request):
        service_only(request)
        payload=await request.json()
        if not isinstance(payload,dict) or set(payload)!={'case_id','report_sha256'}:
            raise HTTPException(422,'Exact verified report binding required')
        case=registry._id(payload['case_id']); digest=payload['report_sha256']
        if not isinstance(digest,str) or not re.fullmatch('[a-f0-9]{64}',digest):
            raise HTTPException(422,'Exact report SHA-256 required')
        def register_sync():
            headers={'Authorization':'Bearer '+config['primary_token']}
            meta=json.loads(local_json(PRIMARY+'/api/v1/cases/'+case,headers))
            raw=local_json(PRIMARY+'/api/v1/cases/'+case+'/revisions/1',headers)
            if meta['case_id']!=case or meta['revision']!=1 or meta['payload_sha256']!=digest or sha256(raw).hexdigest()!=digest:
                raise HTTPException(409,'Primary report binding mismatch')
            registry._query('SELECT retail.p12_register_report(%s,%s::jsonb,%s,%s)',
                (case,json.dumps(meta['request']),raw.decode('utf-8'),digest),True)
            value=owner.issue(case,'p12-request-'+UUID(case).hex,{'report_revision':1,'report_payload_sha256':digest,'predecessor_request_id':None})
            identity=value['request']['proposal_id']
            return {'status':'AWAITING_APPROVAL','case_id':case,'request_id':identity,'report_sha256':digest,
                    'review_url':UAT_BOUNDARY.origin+'/portal/cases/'+case+'/requests/'+identity}
        return JSONResponse(await run_in_threadpool(register_sync),headers=HEADERS)

    def advance_sync(identity):
        value=state._query('SELECT retail.p12_decision_state(%s)',(identity,))
        if value is None or value['request_id']!=identity:
            raise HTTPException(404,'Demo request not found')
        status=terminal(value['decision'],value['publication_id'])
        receipt=None
        if value['decision']=='approved':
            action=worker_store._id(value['action_id']); key='p12-accept-'+UUID(action).hex
            observed=worker.state(action,key)
            if observed['status']=='published':
                receipt=observed['receipt']
            elif observed['status']=='pending':
                receipt=worker.accept(action,key,{n:value[n] for n in ('case_id','request_sha256','report_sha256')})['receipt']
            else:
                raise HTTPException(409,'Publication cannot proceed; original approval is no longer current')
            status='PUBLISHED'
        return {'status':status,'decision':value['decision'].upper(),'request_id':identity,'case_id':value['case_id'],
                'action_id':value['action_id'],'report_sha256':value['report_sha256'],'publication':receipt}

    @app.post('/api/demo/advance')
    async def advance(request:Request):
        service_only(request)
        payload=await request.json()
        if not isinstance(payload,dict) or set(payload)!={'request_id'}:
            raise HTTPException(422,'Exact request identity required')
        identity=state._id(payload['request_id'])
        return JSONResponse(await run_in_threadpool(advance_sync,identity),headers=HEADERS)

    path='/portal/cases/{case_id}/requests/{request_id}/decision'
    # Replace only the route action after installing the unchanged middleware/store.
    app.router.routes=[r for r in app.router.routes if getattr(r,'path',None)!=path]
    @app.post(path,include_in_schema=False)
    async def decide(case_id:str,request_id:str,request:Request):
        await run_in_threadpool(owner.decide,request.state.portal_digest,case_id,request_id,request.state.portal_form)
        try:
            await run_in_threadpool(local_json,HOOK,{'Content-Type':'application/json'},
                                    {'request_id':str(UUID(request_id))})
        except HTTPException:
            # The decision is already committed; never claim publication or retry it blindly.
            pass
        return RedirectResponse('/portal/demo/cases/'+case_id+'/requests/'+request_id,303,headers=HEADERS)

    @app.get('/portal/demo/cases/{case_id}/requests/{request_id}',include_in_schema=False)
    async def result(case_id:str,request_id:str,request:Request):
        value=await run_in_threadpool(owner.review,request.state.portal_digest,case_id,request_id)
        decision=value['decision']; publication=value['publication']
        status=terminal(decision,publication) if decision else 'AWAITING_APPROVAL'
        content='<h2>'+escape(decision.upper() if decision else status)+'</h2><p>Publication: '+escape(status)+'</p>'
        content+='<p><a href="/portal/cases/'+str(UUID(case_id))+'/requests/'+str(UUID(request_id))+'">Request, report and publication receipt</a></p>'
        content+='<p>Create another report by executing the P1.2 Create Report workflow in n8n.</p>'
        content+='<p><a href="/portal">All review requests</a></p>'
        if decision=='approved' and publication is None:
            content+='<p>The human decision is saved. Publication is not confirmed; inspect the n8n decision execution before retrying.</p>'
        return _html('Human Approval result',content+owner.session_html(request.state.portal_csrf))
    app.add_middleware(DemoCopy)
    # F2 is inert until separately authorized configuration/deployment.
    if 'f2_creation' in config:
        from api.f2_creation import F2Middleware, configured_creation
        app.add_middleware(F2Middleware, creation=configured_creation(owner, config))
    return app


def application():
    return build_app(json.loads(CONFIG.read_text(encoding='utf-8')))
