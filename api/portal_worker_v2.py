"""Fixed isolated service worker, no owner/legacy publisher or main activation."""
from datetime import datetime
import re

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from api.main import GuardMiddleware
from api.portal import HEADERS, HEX
from api.portal_publication import IsolatedPortalPublicationStore, PortalOutcomeUncertain, TARGET
from api.portal_review_v3 import _service_key, _service_payload


class IsolatedPortalWorker:
    def __init__(self, store):
        if not isinstance(store, IsolatedPortalPublicationStore):
            raise ValueError('Isolated worker store required')
        self.store=store

    def validate(self, value, action, key, expected=None):
        if value is None:
            raise HTTPException(404,'Approved outbox action not found')
        try:
            saved=value['snapshot']; r=self.store.request_binding(saved)
            observed=datetime.fromisoformat(value['observed_at'])
            created,expires=(datetime.fromisoformat(r[n]) for n in ('created_at','expires_at'))
            if observed.tzinfo is None or saved['action_id']!=action or saved['decision']!='approved' \
                    or type(saved['is_current']) is not bool or saved['dispatch_enabled'] is not False:
                raise ValueError()
            self.store._id(saved['decision_id']); self.store._id(r['reviewer_id'])
            receipt=None
            if saved['publication'] is not None:
                if value['acceptance_key']!=key:
                    raise ValueError()
                receipt=self.store.receipt(saved,action)
                if observed<datetime.fromisoformat(receipt['publication']['accepted_at']):
                    raise ValueError()
                status='published'
            else:
                if value['acceptance_key'] is not None:
                    raise ValueError()
                status='superseded' if not saved['is_current'] else 'expired' if observed>=expires else 'pending'
                if observed<created:
                    raise ValueError()
            result={'contract_version':'portal-worker-state-v1','action_id':action,'acceptance_key':key,
                'key_bound':receipt is not None,'case_id':r['case_id'],'request_id':r['proposal_id'],
                'request_sha256':saved['request_sha256'],'report_sha256':r['report_payload_sha256'],
                'revision':1,'target_id':TARGET,'status':status,'created_at':r['created_at'],
                'expires_at':r['expires_at'],'observed_at':value['observed_at'],'receipt':receipt}
            if expected and any(result[n]!=v for n,v in expected.items()):
                raise ValueError()
            return result
        except (ValueError,TypeError,KeyError,AttributeError,HTTPException):
            raise HTTPException(503,'Invalid stored worker binding') from None

    def identity(self, action, key):
        action=self.store._id(action)
        if not isinstance(key,str) or not re.fullmatch(r'[A-Za-z0-9_-]{8,128}',key):
            raise HTTPException(422,'Original acceptance key required')
        return action

    def state(self, action, key):
        action=self.identity(action,key)
        value=self.store._query('SELECT retail.api_worker_portal_state_v2(%s,%s)',(action,key),
                               validate=lambda v:self.validate(v,action,key),locks=True)
        return self.validate(value,action,key)

    def accept(self, action, key, payload):
        action=self.identity(action,key)
        if not isinstance(payload,dict) or set(payload)!={'case_id','request_sha256','report_sha256'}:
            raise HTTPException(422,'Exact worker binding required')
        case=self.store._id(payload['case_id'])
        for name in ('request_sha256','report_sha256'):
            if not isinstance(payload[name],str) or not HEX.fullmatch(payload[name]):
                raise HTTPException(422,'Exact worker binding required')
        def validate(v):
            result=self.validate(v,action,key,payload)
            if result['status']!='published':
                raise HTTPException(503,'Committed acceptance unavailable')
        value=self.store._query('SELECT retail.api_worker_accept_portal_v2(%s,%s,%s,%s,%s)',
            (action,key,case,payload['request_sha256'],payload['report_sha256']),True,validate)
        return self.validate(value,action,key,payload)


def install_isolated_worker_v2(app, worker, worker_token):
    if not isinstance(worker,IsolatedPortalWorker) or not isinstance(worker_token,str) or not HEX.fullmatch(worker_token):
        raise ValueError('Isolated worker and generated credential required')
    app.add_middleware(GuardMiddleware,token=worker_token)

    @app.exception_handler(PortalOutcomeUncertain)
    async def unknown(request,error):
        return JSONResponse({'detail':'Acceptance outcome unknown; reconcile the original action and key before retry'},503,headers=HEADERS)

    def service_only(request):
        if request.scope.get('query_string') or any(k.lower() in (b'cookie',b'origin') for k,v in request.scope['headers']):
            raise HTTPException(400,'Worker service request required')

    @app.get('/api/v3/portal-actions/{action_id}',include_in_schema=False)
    async def state(action_id:str,request:Request):
        service_only(request)
        return JSONResponse(await run_in_threadpool(worker.state,action_id,_service_key(request)),headers=HEADERS)

    @app.post('/api/v3/portal-actions/{action_id}/accept',include_in_schema=False)
    async def accept(action_id:str,request:Request):
        service_only(request)
        key,payload=await _service_payload(request)
        return JSONResponse(await run_in_threadpool(worker.accept,action_id,key,payload),headers=HEADERS)
